# Probes — what Culprit will ask your running system, and what it will not

A *fact* is a claim about how something is meant to be, or how an
environment is set up to be. A **reading** is what happened when Culprit
actually went and measured, at a point you chose, at a moment you can name.

Comparing descriptions catches a great deal — a route the code declares
and the deployment does not have, a column the ORM maps and the database
lacks. It cannot answer the question that matters during an incident:
*can A actually reach B, from where A sits, right now?* That needs a
socket, and that is what a probe is.

```
culprit probe --list
culprit probe connection:orders-api->payments-api --env staging
culprit probe component:orders-api --env prod \
    -p probe.net.tls_validity --input host=orders.example.com --input port=443
```

## The four verdicts

| Verdict | Means |
|---|---|
| `pass` | The probe ran and the thing it measures is as expected. |
| `fail` | The probe ran and established that it is not. This is a finding. |
| `inconclusive` | The probe ran and **could not establish the answer**. |
| `refused` | The capability was not granted, so nothing was attempted. |

The last two are the ones that make this worth trusting. A tool that can
only say pass or fail has to guess whenever reality is unclear, and a
guess that reads like a measurement is worse than silence. So:

- A TCP connection that is **actively refused** is `fail` — the port is
  definitively closed.
- A TCP connection that **times out** is `inconclusive` — a dropped packet
  does not prove a port is closed, and saying it does would send someone
  to fix the wrong thing.
- A probe with no endpoint to aim at is `inconclusive`, never `pass`.
- A probe whose grant is missing is `refused`, and the report says which
  grant, so "I could not check this" never looks like "this is fine".

Every probe in the catalogue has a test fixture for all three of `pass`,
`fail` and `inconclusive`. That is enforced structurally: a probe added
without an inconclusive fixture fails
`TestEveryProbeHasAllThreeVerdictFixtures` by name.

## What no probe can do

- **No probe writes.** `effect: mutate` fails manifest validation, in Go
  and in Python, and is refused again at catalogue registration. There is
  no `*.write` capability in the permission model to permit one; adding
  one needs its own plan document, not a probe.
- **No synthetic transaction against a write endpoint**, in this or any
  later phase. The HTTP client has no method that sends a body and no
  method other than `GET` and `OPTIONS` — not as a setting, but because
  the other methods are unsayable.
- **No response body is kept.** Schema conformance reads a response's
  top-level *field names* and discards the rest. A body on a real system
  is user data; a probe that kept one would turn a diagnostic file into a
  disclosure.
- **No token material is logged.** Auth probes report a token's audience,
  issuer and expiry — because a wrong audience is the finding — and never
  the signature or the assembled token. A test runs both auth probes
  against a fixture token, confirms the token really was sent, and greps
  the entire serialised output for it and each of its segments.
- **Nothing is chosen for you.** This release runs the probes you name.
  There is no automatic selection and no fault tree; that is the next
  phase, and shipping it early would mean a tool that looks like it is
  reasoning when it is guessing.

## The catalogue

Every probe declares the capabilities it needs. The runner asks the
capability ledger *before* anything is dialled, so an ungranted probe
costs the system under test nothing at all.

`Expects` is the plane the probe's expectation comes from. A probe whose
expectation is INTENT reports `inconclusive` rather than a verdict when no
INTENT fact backs the subject — "this route answers 404" is only a
finding if something declared the route, and "this route answers 200" is
only conformance if something declared it too. Where expectations come
from is the next section.

| Probe | Inputs | Effect | Needs | Expects | Fails when |
|---|---|---|---|---|---|
| `probe.net.dns_resolve` | `host` | inspect | `net.dns.resolve` | CONFIGURED | the name resolves to no address |
| `probe.net.tcp_connect` | `host`, `port` | inspect | `net.tcp.connect` | CONFIGURED | the connection is **actively refused** (a timeout is inconclusive) |
| `probe.net.tls_validity` | `host`, `port` | inspect | `net.tls.inspect`, `net.tcp.connect` | CONFIGURED | the certificate is expired, expiring within 30 days, or untrusted |
| `probe.http.reachable` | `url` | interrogate | `net.http.outbound` | CONFIGURED | the service answers 5xx, or the connection is refused (a timeout or a 4xx is inconclusive) |
| `probe.http.route_conformance` (v2) | `url`, or an `http:` target + `base_url`; `method` | interrogate | `net.http.outbound` | INTENT (`exists`) | a **declared** route answers 404, or 405 for its declared method |
| `probe.http.schema_conformance` | `url`, `expect_fields` | interrogate | `net.http.outbound` | INTENT | a declared response field is absent |
| `probe.auth.token_shape` | `token` or `token_env`, `expect_audience`, `expect_issuer` | inspect | *none*; `config.inspect.values` for the key, when it reads `token_env` | INTENT | the token is expired, not yet valid, or carries the wrong audience or issuer |
| `probe.auth.propagation` | `url`, `token` | interrogate | `net.http.outbound` | INTENT | the downstream answers 401 or 403 |
| `probe.db.connect` (v2) | *none* — the target names the database | inspect | `db.metadata.read` | CONFIGURED | a read-only connection is refused |
| `probe.db.schema_conformance` (v2) | a `schema:` target, or `table`, `schema`; optional `expect_columns` | inspect | `db.metadata.read` | INTENT (`columns`) | the live table lacks a column the declaration maps, or does not exist |
| `probe.db.statement_budget` | *none* — the target names the database | inspect | `db.stats.read`; `db.plan.read` to judge by a table's budget | INTENT (`query_mean_ms_max`) | a statement's time over a 30-second window, against its calls, is over its budget (below) |
| `probe.db.plan` | `queryid` — supplied by the walk only | inspect | `db.plan.read` | *none* — evidence | never: it reads a generic plan; inconclusive without one (below) |
| `probe.config.present` (v2) | `key`, or a `config:` target | inspect | `config.read.names` | INTENT (`required`) | a key the code reads with no default is not set |
| `probe.dep.version` (v2) | `package`, or a `dep:` target; optional `expect_version` | inspect | `repo.read`, plus the packages command on `process.exec.allowlist` | INTENT (`version`) | the installed version differs from a declared **exact pin**, or is absent |
| `probe.edge.impedance` | *none* | observe | `telemetry.metrics.read` | *none* | the connection's latency or error rate is ≥ 3 standard deviations from its own history |
| `probe.http.latency` | `url`, or an `http:` target + `base_url` | interrogate (metered) | `net.http.outbound` | INTENT (`latency_p95_ms`, `latency_p50_ms`) | the declared budget's percentile is over budget at 90% confidence; one reading per budget on the route (below) |

Inputs are supplied with `--input key=value`, repeated. A list input
(`expect_fields`, `expect_columns`) is built by repeating the same key:

```
culprit probe component:orders-api --env staging \
    -p probe.http.schema_conformance \
    --input url=https://orders.example.com/orders \
    --input expect_fields=id --input expect_fields=total_cents
```

**Data sources (Phase 31.1).** With `--env`, the database, config and
dependency probes read that environment through the same machinery
`culprit env capture` uses, so a probe and a capture cannot read one
environment differently:

- **database** — `capture.PostgresReader`: pgx, a read-only session,
  `pg_catalog`. The target names the database (`schema:orders-db/...`,
  or a component); the connection string is read from the variable that
  component's `database: dsn_env:` names, in the environment `culprit`
  runs in. **A DSN is never a probe input** — version 1 took `--input
  dsn=`, which put a credential in shell history and every process
  listing.
- **config** — the environment's adapter (`compose`, `kubernetes`,
  `process`, `exec`). Presence only; the values the adapter sees are
  dropped unread. An environment the adapter could not fully enumerate
  makes an absent key `inconclusive`, not `fail`.
- **dependencies** — the component's declared `packages:` command, which
  must also be on `process.exec.allowlist`, exactly as for a capture. An
  unlisted command is `refused`, and the refusal is recorded.

Without `--env` there is no environment to read, and these probes say so.
`probe.edge.impedance` has no CLI source and will not get one: its
readings are produced by the worker, which has the telemetry
(`docs/LIMITS.md`).

## Latency against a budget — `probe.http.latency`

Phase 36. A latency is only a finding against a declared budget: a
`budgets:` entry in `culprit.yaml`, or an OpenAPI operation's
`x-culprit-budget` (the README's "Latency budgets"). With no budget, the
probe sends nothing and is `inconclusive`. A route with both budgets is
measured once and gives two readings, one per budget, judged from the same
samples.

What it sends, and nothing else:

- **GET only, one fixed count.** 50 requests for a `latency_p95_ms`
  budget, 20 for a `latency_p50_ms`, sequentially, each at least 50 ms
  after the last one ended. No input, `probes:` setting or manifest raises
  the count above 50 or narrows the spacing; a test tries each.
- **No credential, no body, no OPTIONS or HEAD.** A route that is not `GET`
  is `inconclusive` with nothing sent. A route that answers 401 measures
  the refusal, not the route, so its budget is `inconclusive`.
- **A new connection per request,** timed from dialling to the last byte of
  the response (or its first 1 MiB); the connection's setup (name resolution, TCP, TLS) is
  recorded separately in `connect_us`, and for a request that timed out
  after its connection completed, in `timeout_connect_us`. No redirect is
  followed.
- **The budgeted route, exactly.** The URL's path must be the budget's
  route as sent — no escape, empty segment, query, fragment or userinfo
  (LIMITS, "The probe's URL must be the budgeted route").

A **sample** is a `2xx` answer or a timeout. Each request's timeout is
twice the budget plus 500 ms (cut to what is left of the probe's 120 s run),
and a timeout counts as slower than the
budget. Anything else is not a sample (`not_samples` counts them).

The verdict is a pure function of the reading, so the reading carries the
rule's inputs: every sample in `samples_us`, the timeouts, the request
count, how many requests the run planned (`planned`: a run cut short by its
deadline is `inconclusive`, whatever its samples say), and the budget in
`expected`. The rule (`culprit_model.latency`,
`model.JudgeLatency`) takes the nearest-rank percentile and its bounds at
the ranks the exact binomial gives for **90% confidence on each side**, in
integer arithmetic:

- **fail** when even the lower bound is over the budget;
- **pass** when even the upper bound is within it;
- **inconclusive** otherwise — the interval straddles the budget, or there
  are too few samples for a bound to exist.

At 90%, a p95 can be shown within budget only from 45 samples, so a p95
budget passes only when the slowest of its 50 samples is within it. Go,
Python and the API each refuse a latency reading whose verdict its own
samples and budget do not give (`shared/tests/latency_conformance.json`).

From inside the demo's order-service container, as the fault library runs
it against the budget in `demo-services/culprit.yaml` (inventory-service's
port is not published to the host):

```
culprit probe 'http:inventory-service/GET /ready' -f culprit.yaml --env faults-order \
    -p probe.http.latency --input base_url=http://inventory-service:8002
```

`culprit probe <target>` with no `-p` runs every probe, this one included:
against a target with a budget, that is up to 50 requests.

### In the walk

Since Phase 36 part 2 the probe discriminates `latency_budget_exceeded`.
`culprit diagnose` runs it only after the error pass has found nothing,
on each component on the request path that declares a budget a `GET` can
measure, in subject order, from where the binary runs; a failing reading
supports the hypothesis, all passing rule it out for that component alone.
The slow reading's setup and server times then tell the connection from
the component (LIMITS, "Latency in the walk"). The walk's remaining wall
clock is the probe's deadline. `culprit verify` runs it again, once per
round for both of a route's readings.

## Statements and plans — `probe.db.statement_budget`, `probe.db.plan`

Phase 37 part 2. A budget on a statement is `query_mean_ms_max` in
`culprit.yaml`'s `budgets:`, in whole milliseconds, on a table
(`schema:<database>/<namespace>.<table>`, no column) or on the database's
component — a component of kind `database` the file declares.

**The statement probe** takes two snapshots of the database's
`pg_stat_statements`, 30 seconds apart, in one read-only session — the
window is fixed, and the walk's deadline cuts it. For each normalised
statement called in the window it has the change in calls and in total
execution time, converted once to whole microseconds. Only this database's
statements are read (its `dbid`), never those of the role Culprit connects
as. The rule is integer comparison:

- **fail** when a statement's `total_us > budget_ms × 1000 × calls`;
- **pass** when every statement with a budget is within it;
- **inconclusive** when the statistics were reset, or a statement evicted,
  during the window, or when no call to a budgeted statement fell in it —
  and when the database has no `pg_stat_statements`, saying so.

A statement is judged by the strictest budget of the tables its plan
reads, otherwise by the database's budget. Which tables it reads takes a
plan, so with `db.plan.read` granted the probe plans each statement in the
same session; without it only the database's budget applies, a table's
stays unjudged, and the reading says so. The reading keeps at most 20
statements, those over budget first, then by time in the window, and
counts the rest. A statement's text is kept only when it begins with
`SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE` or `MERGE` — the statements
Postgres stores with every constant replaced by `$n`; any other is listed
by `queryid` with "text not kept". The verdict is re-judged from the
reading's integers in Go, in Python and at `POST /readings`.

**The plan probe** asks the planner how it would run one statement, named
by its `queryid` from the database's own statistics — never by text a
caller gives. Only a `SELECT` or `WITH` is planned; anything else,
including text beginning with a comment, is inconclusive. The plan is
generic: the statement is parsed as a prepared statement and explained,
under `plan_cache_mode = force_generic_plan`, without its parameters'
values, and nothing is executed. The reading keeps each node's type,
relation, index, estimated rows and cost, and the relation's own column
names its filter mentions — never the filter or a constant. It has no
expectation: a sequential scan of a small table is normal, so a plan is
evidence for the walk (Phase 37 part 3), not a finding. Before PostgreSQL
16 it is inconclusive, saying so.

Under `culprit mcp`, `culprit_probe` refuses `probe.db.plan` and any
`queryid`, and any input at all to `probe.db.statement_budget`, before
anything is sent: an agent names no statement, table or address.

## What each probe rules out — `discriminates`

`culprit diagnose` (Phase 32) chooses probes by the `discriminates` field of
their manifests and nothing else: a probe that *passes* on a subject rules
out the hypotheses of the kinds it lists, on that subject. Where two probes
discriminate the same kind, the cheapest runs first, then by id.

| Hypothesis kind | Ruled out by |
|---|---|
| `component_fails` — a request entering here fails | `probe.http.reachable` |
| `connection_unreachable` | `probe.net.tcp_connect` |
| `tls_invalid` | `probe.net.tls_validity` |
| `auth_audience_mismatch` | `probe.auth.token_shape` |
| `auth_rejected` | `probe.auth.propagation` (the walk does not yet generate this hypothesis — docs/LIMITS.md) |
| `contract_mismatch` | `probe.http.route_conformance`, `probe.http.schema_conformance` |
| `config_missing` | `probe.config.present` |
| `database_unreachable` | `probe.db.connect` |

`probe.net.dns_resolve` deliberately discriminates nothing: a name that
resolves says nothing about whether a connection opens, and
`probe.net.tcp_connect` resolves the name itself. The vocabulary is
`model.HypothesisKinds`, held to Python by
`shared/tests/investigation_conformance.json`; a manifest naming a kind the
walk does not know fails validation.

## Where expectations come from

A reading is a measurement against a reference, and the reference is a
fact. `culprit probe` runs the same extraction `culprit check` runs —
the same extractors, the same `invariants:` — and for each probe builds
the subject it measures from the target and inputs (`--input
url=http://orders/orders/42` against `connection:web->orders` measures
`http:orders/GET /orders/42`), then selects the facts on that subject
whose predicate is the one the manifest `produces`:

- A concrete path matches a declared template (`/orders/42` matches
  `/orders/{id}`), and the most specific declared route wins.
- The highest `confidence_rank` (§2.4) is the expectation, and the
  reading's `expected_source` is its provenance — the file, the locator,
  the extractor.
- **Rank picks, it never discards.** When two sources disagree about the
  same subject and predicate, the reading carries the others as
  `intent_conflict` evidence naming each source, its rank and what it
  says.
- A manifest whose `expected_from` is CONFIGURED takes its expectation
  from a capture of the same environment, passed as `--capture
  <envelope>` (`culprit env capture <env> -o <file>`).

An explicit `expect_columns`, `expect_fields` or `expect_version` input
still works, and still wins: it is how a script asks a narrower question
than the code declares.

```
# Is every declared column of this table really there?
culprit probe 'schema:culprit-db/public.users' --env quickstart     -p probe.db.schema_conformance

# Is this declared route really served? (the api's own port, published on
# 127.0.0.1:18000 by infra/docker-compose.probe-demo.yml; through the
# dashboard's proxy it is --input base_url=http://localhost/api)
culprit probe 'http:culprit-api/GET /model/components' --env quickstart     -p probe.http.route_conformance --input base_url=http://127.0.0.1:18000
```

`probe.auth.token_shape` declares no capability because it opens nothing:
handed a token as `token`, it reports the structure of one you already
hold. Named a variable as `token_env`, it reads that service's own
credential in memory, which needs `config.inspect.values` for exactly that
`component/KEY` (docs/PERMISSIONS.md) and is refused without it.

A reading's `grants_used` is what the run exercised, not only what the
manifest declares: a `token_shape` reading that read a credential names
`config.inspect.values`, and a probe that ran an allowlisted command names
`process.exec.allowlist`. A refused reading names none.

`probe.edge.impedance` needs at least **30 observations** before it will
return a verdict at all; below that it is `inconclusive`. A z-score over
four samples is arithmetic, not evidence.

## Why both `culprit env capture` and `probe.net.*` exist

Phase 30 already reads DNS, TCP and TLS for a component's declared
endpoint. Phase 31 adds probes that do, on the face of it, the same three
things. Both are kept, deliberately:

|  | `culprit env capture` | `culprit probe` |
|---|---|---|
| Plane | CONFIGURED — what this environment is set up as | OBSERVED — what happened when we measured |
| Output | a `Fact`, compared later against other facts | a `Reading`, with a verdict and a reason |
| Answers | "is this configured, and how" | "does this work, from here, now" |
| Resolution | yes / no | pass / fail / **inconclusive** / refused |

The verdict column is the real difference. Capture answers yes or no
because it is recording a configuration; a probe must be able to say *I
could not tell*, and collapsing the two would mean either capture growing
a verdict it has no use for, or probes losing the distinction between "the
port is closed" and "the packet vanished".

**The cost, stated plainly:** the low-level dial, resolve and handshake
code now exists in two packages, `internal/capture` and `internal/probe`.
That is two places to audit rather than one, and it is recorded in
`docs/LIMITS.md`. Collapsing them is worthwhile future work; it was not
done here because it means changing `internal/capture`'s interface, which
this phase does not own.

## Configuring probes — `culprit.yaml`

```yaml
probes:
  probe.net.tls_validity:
    enabled: false
    reason: certificates are managed by the platform team
  probe.http.route_conformance:
    timeout_ms: 30000
    environments: [staging]
```

Only three things are configurable here: whether a probe runs, how long it
may take, and where it applies. **Capabilities are not.** Those belong to
the probe's own manifest and to the environment's `grants:` block, because
"what may Culprit do to my system" needs to be answerable by reading one
place.

Disabling a probe requires a `reason`, the same discipline `suppress:` and
`severity_overrides:` follow. A check switched off without a stated reason
is indistinguishable, six months later, from one nobody noticed was off.

A probe id this binary does not recognise is accepted by the manifest and
reported as `inconclusive` at run time. That is deliberate: third-party
probes are a manifest plus an allowlisted `exec` procedure, and a
`culprit.yaml` should stay shareable between a team that has the plugin
installed and a team that does not.

## Exit codes

The same contract every other command keeps:

| Code | Meaning |
|---|---|
| `0` | No probe failed. Inconclusive and refused readings are **not** failures — neither established that anything is wrong. |
| `1` | At least one probe returned `fail`. |
| `2` | Culprit could not run: a bad target, an unreadable manifest, an undeclared environment. |

## Measured again, never reused — `culprit verify`

`culprit verify <investigation-id>` checks a fix by running **every** probe
the investigation ran again — not only the one that failed — each **twice**,
from the request the walk recorded: the same probe, target, inputs and
environment, under the grants that environment has now. A counterfactual
reading taken in a reference environment is taken there again. No stored
reading is reused; every reading in a verification was measured by it.

Re-running only the failing probe, once, is how a fix gets "confirmed" by a
cache, a fault that comes and goes, or a change nobody made on purpose. So
the verdict is `verified` only when every reading that failed passes on
both runs, every reading that passed still passes, and every difference
between the environment at diagnosis and now is explained by the change
named with `--change`. A reading that is `refused` or `inconclusive` now,
or that gives a different verdict on its two runs, keeps it from
`verified`: the verdict is `inconclusive`, unless a reading that failed
still fails (`not_resolved`) or one that passed now fails (`regressed`),
which settle it whatever else is unsettled. The other verdicts are `not_resolved`
(a reading that failed still fails), `regressed` (the fault is gone and
something that passed now fails) and `changed_underneath` (the fault is
gone, and the environment changed in a way the named change does not
explain). Exit codes: `0` verified, `1` any other verdict, `2` could not
run. Its limits are in `docs/LIMITS.md`, "Verification".

An agent does the same as a `verify` task (Phase 34 part 2), for an
investigation it diagnosed: every probe re-run twice, under the grants the
task holds, each run an entry in its audit log. A reading the walk took in a
reference environment is re-run there under no grant — an allowance is per
environment — so it is `refused`. The verification is posted to the control
plane, which judges it again with the same rule and stores it beside the
investigation; the investigation itself is never edited.

## Where readings go

`culprit probe` prints them. `POST /readings` stores them, under the
`probe-writer` role, which can insert into `readings` and do nothing else —
and since Phase 33 it takes an agent's signed request and nothing else:
every reading must name the agent that signed it (`docs/PERMISSIONS.md`,
"Which credential writes what"). A paired `culprit agent` posts the readings
of every probe task it runs; `culprit probe` on its own still only prints.

The control plane can describe the catalogue (`GET /probes`) but cannot
run a probe: probes execute in the `culprit` binary, where the environment
is. `POST /probes/{id}/run` therefore answers `503` with the equivalent
local command. A probe is run remotely by addressing it to a paired agent as
a task (`POST /agents/{id}/tasks`), which runs it under its own grants. That is an honest
not-yet-available rather than a stub that fabricates a reading.
