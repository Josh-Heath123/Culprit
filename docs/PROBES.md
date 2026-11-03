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
expectation is INTENT reports `inconclusive` rather than `fail` when no
INTENT fact backs the subject — "this route answers 404" is only a
finding if something declared the route.

| Probe | Inputs | Effect | Needs | Expects | Fails when |
|---|---|---|---|---|---|
| `probe.net.dns_resolve` | `host` | inspect | `net.dns.resolve` | CONFIGURED | the name resolves to no address |
| `probe.net.tcp_connect` | `host`, `port` | inspect | `net.tcp.connect` | CONFIGURED | the connection is **actively refused** (a timeout is inconclusive) |
| `probe.net.tls_validity` | `host`, `port` | inspect | `net.tls.inspect`, `net.tcp.connect` | CONFIGURED | the certificate is expired, expiring within 30 days, or untrusted |
| `probe.http.reachable` | `url` | interrogate | `net.http.outbound` | CONFIGURED | the service answers 5xx |
| `probe.http.route_conformance` | `url`, `method` | interrogate | `net.http.outbound` | INTENT | a **declared** route answers 404, or 405 for its declared method |
| `probe.http.schema_conformance` | `url`, `expect_fields` | interrogate | `net.http.outbound` | INTENT | a declared response field is absent |
| `probe.auth.token_shape` | `token`, `expect_audience`, `expect_issuer` | inspect | *none* | INTENT | the token is expired, not yet valid, or carries the wrong audience or issuer |
| `probe.auth.propagation` | `url`, `token` | interrogate | `net.http.outbound` | INTENT | the downstream answers 401 or 403 |
| `probe.db.connect` | `dsn` | inspect | `db.metadata.read` | CONFIGURED | a read-only connection is refused |
| `probe.db.schema_conformance` | `dsn`, `table`, `schema`, `expect_columns` | inspect | `db.metadata.read` | INTENT | the live table lacks a column the code maps, or does not exist |
| `probe.config.present` | `key` | inspect | `config.read.names` | INTENT | a key a **declared** INTENT fact requires is not set |
| `probe.dep.version` | `package`, `expect_version` | inspect | `repo.read` | INTENT | the installed version differs from the declared one, or is absent |
| `probe.edge.impedance` | *none* | observe | `telemetry.metrics.read` | *none* | the connection's latency or error rate is ≥ 3 standard deviations from its own history |

Inputs are supplied with `--input key=value`, repeated. A list input
(`expect_fields`, `expect_columns`) is built by repeating the same key:

```
culprit probe component:orders-api --env staging \
    -p probe.http.schema_conformance \
    --input url=https://orders.example.com/orders \
    --input expect_fields=id --input expect_fields=total_cents
```

**Six of the thirteen have no data source in the shipped CLI yet.**
`probe.db.connect`, `probe.db.schema_conformance`, `probe.config.present`,
`probe.dep.version` and `probe.edge.impedance` need a database client, a
config reader, a package reader and a metrics reader respectively, and
the CLI wires only the network and HTTP ones. They return `inconclusive`
with a reason saying so — honestly, but they cannot reach a verdict from
`culprit probe` in this release. `probe.edge.impedance` readings *are*
produced, by the worker, which has the telemetry; see `docs/LIMITS.md`.

`probe.auth.token_shape` needs no capability because it opens nothing: it
reads a token you already hold and reports its structure.

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

## Where readings go

`culprit probe` prints them. `POST /readings` stores them, under the
`probe-writer` role, which can insert into `readings` and do nothing else.

The control plane can describe the catalogue (`GET /probes`) but cannot
run a probe: probes execute in the `culprit` binary, where the environment
is. `POST /probes/{id}/run` therefore answers `503` with the equivalent
local command until an agent transport exists. That is an honest
not-yet-available rather than a stub that fabricates a reading.
