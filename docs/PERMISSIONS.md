# What Culprit can see, and what you are granting when you let it

This is for the person deciding whether to point Culprit at an
environment they care about. It lists every permission Culprit knows
about, what each one lets it read, what it never reads, and what it costs
you not to grant it.

## The short version

- **Culprit never changes anything.** There is no write permission to
  grant. Not a disabled one, not a hidden one: none exists, and naming
  one in `culprit.yaml` (`db.schema.write: true`) is a validation error
  rather than a setting that is ignored.
- **Nothing is granted by default.** An environment with no `grants:`
  gets nothing looked at, and the report says, line by line, what it did
  not look at and which grant would change that.
- **Config values stay where they are.** By default Culprit reads the
  *names* of your environment variables and a coarse description of each
  value (a "shape": a URL, a number, empty or not, which kind of database
  a connection string points at). The value itself is kept only for keys
  you list by name, and even then it never appears in a report.
- **It runs once and exits.** `culprit env capture`, `culprit diff`,
  `culprit diagnose` and `culprit verify` are one-shot commands. The one
  long-running process is `culprit agent`, which you start and grant
  separately (below).
- **It sends no request into your application.** It reads configuration
  and metadata. The network checks stop at a DNS lookup, a TCP handshake,
  or a TLS handshake: no HTTP request, no SQL query against your data.

## Where you grant things

Per environment, in `culprit.yaml`, which you commit and review like any
other file:

```yaml
environments:
  production:
    adapter: compose        # compose | kubernetes | process | exec
    compose:
      project: shop-prod
    grants:
      config.read.names: true
      deploy.metadata.read: true
      db.metadata.read: true
      config.read.values: [orders-api/LOG_LEVEL]   # by name, never "all"
    components:
      orders-api:
        database:
          dsn_env: PROD_DB_URL   # the NAME of a variable, never the connection string
```

`true` grants a permission; anything absent or `false` withholds it. The
three permissions that are granted per item — config values, database
rows, and running a command — take a list and refuse `true`, so that
nothing sensitive can be granted by accident. Wildcards are refused for
the same reason.

## What happens when something is not granted

The check does not run, and the capture records a **refusal**:

```
Refused (2) — not looked at, because the capability was not granted
  production/orders-api  live schema     db.metadata.read is not granted
  production/orders-api  config values   the values of 7 key(s) were not captured — only their shape (config.read.values is not granted)
```

A refusal is part of the capture, travels inside the envelope (covered
by its signature, when you sign it — see "The capture file" below), and
is stored with it. Culprit never presents "I was not allowed to look" as
"I looked and found nothing wrong".

## Every permission

### `config.read.names`

**Reads:** the names of the environment variables a component runs with,
and the *shape* of each value: its type (string, number…), whether it is
empty, a format class (URL, connection string, hostname, port, duration,
credential-shaped…), and, for a URL, which scheme from a fixed list
(`postgresql`, `mysql`, `redis`, `https`…, or `other`). Length is kept
as a coarse class — empty, short (up to 16 characters), medium (up to
128), long — never as a number, and it is only *compared* as empty or
not, since two correct URLs differ in length.

**Never:** the value. To compute the shape Culprit has to look at the
value in memory, once, and it keeps only the shape. The shape type has no
field a value can be put in — this is enforced by the code, not by
convention, and tested by planting real-looking secrets and searching
every output for them.

**Finds:** a variable the code reads and the environment does not set
(`JWT_SECRET_KEY` missing in production), a variable set but empty, a
connection string pointing at a different kind of database in one
environment, a credential baked into a URL in one environment and not
the other.

**Without it:** no environment-variable comparison at all.

### `config.read.values` — per key

**Reads:** the literal value of each key you list, as
`<component>/<KEY>`.

**Where it goes:** into the capture (so two environments' values can be
compared) and into the database if you upload the capture. **Never into
a report**: every report format and every API response prints a config
key's shape, or "(a value, not shown)", whatever the capture holds.

**Grant it for:** keys whose value you need compared and that are not
secret — `LOG_LEVEL`, `FEATURE_FLAGS`, a region. Do not list secrets; the
shape already tells you whether a secret is set and what kind of thing
it is. A bearer token `culprit diagnose` must inspect does not need this
grant, and is not satisfied by it: see `config.inspect.values`.

### `config.inspect.values` — per key

**Reads:** the value of each key you list, as `<component>/<KEY>`, in
memory, so a probe can inspect its structure — today, the audience,
issuer and expiry of a bearer token (`probe.auth.token_shape`).

**Where it goes:** nowhere. Nothing may store or emit the value: not a
capture, not a reading, not a reason, not an investigation. A reading
taken under it names it in `grants_used`.

**Not `config.read.values`.** Storing a value and inspecting one are
different permissions (Phase 33): `config.read.values` does not let a
probe inspect a token, and `config.inspect.values` never lets
`culprit env capture` store one. Granting either never implies the
other.

### `db.metadata.read`

**Reads:** which tables exist and which columns each has, whether each
column is nullable, which columns lead an index (since Phase 37 part 1),
and the Alembic migration version — through the connection string in the
variable `dsn_env` names, in the shell Culprit runs in. The session is
opened read-only, with a statement timeout.

**What it sends:** four fixed statements and nothing else. The binary has
one file that can open a database connection, and it sends only
statements from a closed set written into that file; anything else — an
arbitrary query, an `EXPLAIN ANALYZE` — is refused before it leaves.
Values travel as bind parameters. Every session sets
`default_transaction_read_only = on` and a ten-second
`statement_timeout` as connection parameters, so were the first two
layers to fail, Postgres itself would refuse a write (a test sends one
and sees it refused).

**Never:** rows. The only row read is the migration version in
`alembic_version`, which is the one row §0.4 of the plan names as
metadata. Column *types* are not compared either (see
docs/LIMITS.md).

**Which database role to use:** the least privileged one you have. The
table list comes from `pg_catalog`, which any role can read, so a role
with no table privileges at all still produces a complete, correct
schema. Reading the migration version needs `SELECT` on
`alembic_version`; without it, the capture says the version was not read
rather than guessing.

**Finds:** a live schema behind the migration head (the deploy shipped
the code and nobody ran the migration), a table the code maps that the
database does not have, and an index the migrations declare that the
database lacks, or the reverse.

### `db.stats.read`

**Phase 37 part 1: declared, used by nothing yet.** Part 2's statement
probe will use it. It will let Culprit read the database's own statistics
— `pg_stat_statements` (each normalised statement's call count and time),
`pg_stat_user_tables` and `pg_stat_user_indexes` (how each table and
index is scanned). Statement text in `pg_stat_statements` is normalised
— constants replaced by placeholders — and every piece of it passes
through the same credential redaction as every other piece of text
before it goes anywhere. Culprit never resets these statistics: that is a
write. Implies no other capability.

### `db.plan.read`

**Phase 37 part 1: declared, used by nothing yet.** Part 2's plan probe
will use it. It will let Culprit ask the planner how it would run one
statement — `EXPLAIN (GENERIC_PLAN, FORMAT JSON)` and nothing else, which
plans without executing anything. `EXPLAIN ANALYZE`, which runs the
statement, is refused before it is sent. It does not imply
`db.rows.read`, and no capability implies it (a test grants each
capability alone and finds every other withheld).

### The recommended database role, and what it reveals

For `db.metadata.read` alone, any role will do (above). For the two
Phase 37 capabilities, Postgres sets the floor:

- reading another role's statement text in `pg_stat_statements` needs
  **`pg_read_all_stats`**;
- planning a statement needs **`SELECT` on every table it names**:
  Postgres plans only what the role could run.

So the role `db.plan.read` needs **can read rows**, whatever Culprit
chooses to send. Culprit never sends a statement that returns a row — the
template set holds that, and the session is read-only — but the grant
on the role is what a stolen credential would carry, as it is for a
Kubernetes role that can read Secrets. Use a role made for this, with
`SELECT` on the application's tables and nothing else, and give its
password to nothing but Culprit. `db.rows.read` stays a separate
capability, implied by nothing.

### `db.rows.read` — per table

**Nothing in this release reads rows.** The permission exists because the
plan names it; granting it changes nothing today, and the capture
records it as granted-and-unused so you can see that.

### `deploy.metadata.read`

**Reads:** which image each component runs — the reference as
configured (`ghcr.io/acme/orders:1.4`) and its registry digest — through
`docker inspect` or the Kubernetes API, using your own `docker` or
`kubectl` credentials.

**Finds:** two environments running different builds of the same
component, including the same tag pushed twice.

### `process.exec.allowlist` — per command

**Runs:** a command you declare under the environment's `exec:` section,
exactly as written (no shell), and reads its output. Used for installed
package versions (`pip freeze`, `npm ls --json`) and, with the `exec`
adapter, for reading an environment Culprit has no adapter for.

A command declared but not on the allowlist is refused when
`culprit.yaml` is loaded, so a forgotten grant fails loudly rather than
looking like a clean result. The command's error output is never read
into a report.

### `net.dns.resolve`, `net.tcp.connect`, `net.tls.inspect`

For a component's declared `endpoint` (a host and a port):

- **`net.dns.resolve`** — does the name resolve. Asks a resolver; the
  endpoint is not contacted.
- **`net.tcp.connect`** — does a TCP handshake complete. Closed
  immediately; no application data is sent.
- **`net.tls.inspect`** — is the certificate valid, expiring within 30
  days, expired, or untrusted. Needs `net.tcp.connect` too, since a TLS
  handshake is a TCP connection first. Closed immediately after the
  certificate is presented; no HTTP request is made.

### `net.http.outbound`

**Used since Phase 31.** This is the one grant that lets Culprit make an
application request to your running service, and it is what
`probe.http.reachable`, `probe.http.route_conformance`,
`probe.http.schema_conformance`, `probe.auth.propagation` and, since
Phase 36, `probe.http.latency` need.

What it permits is deliberately narrow: `GET` and `OPTIONS` only. The
HTTP client has no method that can send a body and no way to express any
other verb, so no probe can write to your system under any grant — there
is no `*.write` capability and no `effect: mutate` probe. Responses are
read for their status, content type and top-level JSON **field names**;
no response body is kept. At most 3 redirects are followed and at most
1 MiB is parsed.

**`probe.http.latency` needs no new capability.** Under this grant it
sends a fixed number of plain `GET` requests to the one route a declared
budget names: 50 for a p95 budget, 20 for a p50, one at a time, at least
50 ms apart, each on a new connection, with no header beyond the
defaults, no body and no credential. It follows no redirect, reads each
response to its last byte or the same 1 MiB cap, whichever comes first, and keeps only the
status class, the time each took and the connection setup time — never a
header value or a byte of the body. No setting raises the count. That is
more requests than any other probe makes, which is why its manifest says
`cost: metered`; withhold `net.http.outbound` and it sends nothing.

Since Phase 36 part 2, `culprit diagnose` sends these requests too, under
the same grant: one run per component on the request path that declares a
budget, and only after every error probe has passed — so a walk that finds
no error can make up to 50 requests per budgeted component, plus one more
run to see the root fail again. `culprit verify` repeats each run twice. A
route with both budgets is still one run. Every request is built in one
place, which refuses any method but `GET` and `OPTIONS` before the request
exists; through `culprit mcp` the address must be the endpoint of the
component whose budget is judged.

Withhold it and every HTTP probe reports `refused`, naming this grant.

### `repo.read`, `telemetry.metrics.read`

**Used since Phase 31.** `probe.dep.version` needs `repo.read` to compare
an installed dependency version against the declared one;
`probe.edge.impedance` needs `telemetry.metrics.read` to read the
deviation the anomaly scorer has already computed for a connection.

Both are read-only, and neither is wired to a source in the shipped CLI
yet — see `docs/LIMITS.md`, "Six probes have no data source in the CLI".
Granting them today therefore changes nothing in practice, but they are
no longer unused *by the model*, and a future release will make them
live without changing this document.

### `model.read`, `telemetry.logs.read`, `telemetry.traces.read`

Named by the plan for later phases (the production agent). No code in
this release uses them; granting one changes nothing and is recorded as
unused.

## Reading a token for `culprit diagnose` — `tokens:` and `config.inspect.values`

`environments.<env>.components.<caller>.tokens` names, for each component
the caller presents a bearer token to, the *variable* holding that token
in the environment `culprit diagnose` runs in. Naming it grants nothing.
Reading it is reading a credential, so it is behind `config.inspect.values`
for that exact key (Phase 33; it was `config.read.values` until then):

```yaml
grants:
  config.inspect.values: [order-service/INVENTORY_TOKEN]
```

With the grant, `probe.auth.token_shape` reads the variable itself and
reports only the token's audience, issuer and expiry; the token never
reaches a reading, a reason or the investigation, and the fault library
asserts that on every fault, in JSON and in text. Without it — or with a
grant for some other key — the probe is **refused**, the audience
hypothesis is left unexplored, and the diagnosis is partial and names the
missing grant. `config.read.values` for the same key does not count, and
`config.inspect.values` never lets `culprit env capture` record the
token's value.

## The agent's grants — `culprit agent`

`culprit agent` (Phase 33) does not read the grants in `culprit.yaml`.
Its authority is its own configuration file, written by whoever runs it
and listing grants explicitly per environment:

```yaml
version: 1
agent_id: prod-eu-1
manifest: ./culprit.yaml     # the system model; its grants are ignored here
environments:
  production:
    grants:
      net.dns.resolve: true
      net.tcp.connect: true
      config.inspect.values: [order-service/INVENTORY_TOKEN]
```

The file is read again before every task, so removing a grant takes
effect on the next task with no restart. The parser refuses a wildcard
(`net.*`, `"*"`, an item containing `*`), `all`, any `*.write`, and any
name that is not a capability, each with its line. A task may carry an
allowance that narrows these grants for that one task; it can never add
one. A task that needs a grant the agent does not hold is refused before
anything is dialled; the refusal is a reading and an entry in the agent's
audit log.

## The minimum grants for each kind of investigation

What an agent needs to *complete* a diagnosis of each class of fault — to
find the root and rule out every other explanation the walk can test.
With less, the investigation still runs, and ends **partial**: it says
where it stopped, and names the grant it lacked.

<!-- cli/cmd/culprit/grantsets_test.go reads the second column of this table
and runs each class with exactly those grants, then with each one removed.
Change a set here and the test runs the new one. -->

| Investigation class | Minimum grants | Why each is needed |
|---|---|---|
| reachability | `net.tcp.connect`, `net.http.outbound` | `probe.net.tcp_connect` tests the connection itself; `probe.http.reachable` asks the service at the other end whether it fails on its own. |
| schema | `db.metadata.read` | `probe.db.connect` tests the connection to the database, under a read-only session. No row is read. The walk's database hypothesis is that connection; `probe.db.schema_conformance`, which compares live columns with the migrations, needs the same grant and runs as a probe of its own. |
| auth and audience | `config.inspect.values`, `net.tcp.connect`, `net.http.outbound` | `probe.auth.token_shape` reads the caller's token in memory — `config.inspect.values` for that one variable (`<caller>/<VARIABLE>`), never stored — to check its audience; the other two rule out the connection and the callee. |
| configuration | `config.read.names` | `probe.config.present` checks that a required key is set where the service runs. Names only; no value is read. |

Each set is for that class on its own: one service and the one thing it
depends on. **A real request path adds the grants of every other edge on
it** — a path with an HTTP hop before the database needs the
reachability set as well as `db.metadata.read`, because the walk must rule
that hop out before it can blame the database. `net.dns.resolve` and
`net.tls.inspect` are in no minimum set: a name that resolves rules
nothing out, and a TLS check applies only to an endpoint declared
`tls: true` — grant `net.tls.inspect` for those.

## Verifying a fix — `culprit diagnose`, `culprit verify` and an agent

Verification asks for no permission of its own. It uses the grants the
environment already has — or, through an agent, the grants that agent holds
there, narrowed by the task's allowance, exactly as its probes do — in two
places:

- **`culprit diagnose` now captures the environment before it walks** —
  the same capture `culprit env capture` takes, under the same grants
  (`config.read.names`, `deploy.metadata.read`, `db.metadata.read`, the
  `net.*` checks), with the same refusals. It is the record of the
  environment as diagnosis found it, kept for `culprit verify` to compare
  with. An environment that grants none of them gets no record, and the
  investigation says so: its verification can then be `inconclusive` at
  best.
- **`culprit verify` runs every probe the investigation ran again,** under
  the grants `culprit.yaml` gives that environment *now*. A grant removed
  since the diagnosis makes its probe `refused`, and the verdict
  `inconclusive`. A grant *added* since lets a probe that was refused at
  diagnosis really run now — and it changes what the capture can see, so
  the comparison may report a difference that is the grant, not the
  environment (`changed_underneath`: cautious, never a false `verified`).
  No probe is run that the walk did not run: the same probe, target and
  environment, with the inputs it recorded.

What diagnose keeps — the investigation, the request behind each reading,
and the capture — is written to the state directory (`--state-dir`,
`$CULPRIT_STATE_DIR`, else your user's state directory), readable by you
alone. The capture is the same envelope `culprit env capture` writes, so
it carries the literal value of any key `config.read.values` allowlists.

**Through an agent** (Phase 34 part 2), the same happens inside the agent:
every walk it runs captures before, under its own grants, and keeps the
record in its state directory (`state/` beside its audit log). An admin
asks it to verify with a `verify` task, naming the change and saying
whether the fault was planted; the task is addressed like any other and
runs under the same narrow-only allowance. Every probe it re-runs is an
audit entry. It posts the verification to `POST
/investigations/{id}/verifications`, signed; asked about an investigation it
did not diagnose, it measures nothing and answers `inconclusive`.

## The agent and the control plane — keys, pairing, allowances

A paired agent proves who it is with an **Ed25519 key** it generates itself
(`culprit agent init`, written `0600`, never overwritten). Every request it
sends is signed over its method, its path, a digest of its body, a
timestamp and a single-use nonce; the control plane refuses a request it
cannot verify, one more than **300 seconds** from its clock, or one whose
nonce it has seen, and does not say which — and it checks the signature
over the raw body before it parses a byte of it. The private key never
leaves the agent's file: pairing sends only the public half. The control
plane is reached over **https**: the agent refuses a plain-`http`
`control_plane.url` unless it is a loopback address or the configuration
sets `allow_plain_http: true`, which it reports at every start.
`deploy/agent/` has a recipe for Docker, Compose, Kubernetes and systemd;
`docs/SECURITY.md` says what each compromise can and cannot do.

**Pairing.** An admin makes a code (Settings → Agents, or `POST /agents/pairing-codes`); it works
once and expires after **15 minutes**, and only its SHA-256 is stored.
`culprit agent pair --code` spends it, registering the agent's id, public
key and the grants its configuration gives in each environment.

**Allowances.** A newly paired agent is allowed nothing. An admin sets,
per environment, which of the grants the agent reported it may use
(`PATCH /agents/{id}/grants`); naming a grant it did not report, a
wildcard or `all` is refused. On Settings → Agents each grant is shown in
plain words, and a change is shown as a diff before it is saved. The allowance is stamped on each task when
the agent claims it, and the agent intersects it with its configuration
again — so either side can withhold a grant on the next task, and neither
can add one. Revoking an agent (`POST /agents/{id}/revoke`) refuses its
very next request.

### Which credential writes what

| Route | Accepts |
|---|---|
| `POST /facts/captures`, `POST /divergences/captures`, `POST /captures` | the project token |
| `POST /investigations` | the project token, or an agent's signature — recorded as `submitted_by` |
| `POST /investigations/{id}/verifications` | the project token, or an agent's signature — recorded as `submitted_by`; an agent's runs must all name it |
| `POST /readings` | an agent's signature only; every reading must name that agent |
| `POST /agents/register` | a pairing code, spent once |
| `/agents/me/...` (claim, result, audit) | the agent's signature |
| every other `/agents` route | an admin's session |

`api/tests/test_route_credentials.py` reads the application's routes and
fails if the project token is accepted anywhere else.

### The agent roles

Three database roles, one per write surface (migration `d7a3e5f1b9c2`):
**`agent-admin`** makes pairing codes, sets allowances, revokes and
addresses tasks; **`agent-registrar`** spends a code and inserts the agent,
nothing more; **`agent-gateway`** looks up keys, records nonces, reads
allowances, claims and completes tasks and appends audit entries. No role
holds UPDATE or DELETE on `agent_audit_log`, and triggers refuse both, and
TRUNCATE, to every role including the owner. **`api-reader`** serves the
agents screen: it reads the agents, their allowances, tasks and audit log,
and two columns of `agent_nonces` — `agent_id` and `seen_at`, never the
nonce itself (`f1a9c3d7e2b4`, narrowing `e5b8a2d4c6f1`'s table grant) —
whose newest row per agent is that agent's last signed request; it writes
none of them.

### The verification role

**`verification-writer`** (migration `f2b7d4e9a1c6`) holds INSERT on
`verifications` and nothing else — not even SELECT. The API checks a
verification against the stored investigation under `api-reader` first,
then inserts it under this role; it never writes to the investigation. No
role holds UPDATE or DELETE on `verifications`, and triggers refuse both,
and TRUNCATE, to every role including the owner. `api-reader` reads it for
the investigation page and `GET /outcomes/accuracy`.

## The narrator — what it reads, and what it sends

Narration is off unless `LLM_PROVIDER` in `infra/.env.prod` says otherwise
(Phase 35 part 2; the README's "Narration, if you want it").

### The narrator role

**`narrator`** (migration `a6c2e9d4f8b1`) is the worker's narration job.
It holds SELECT on the five investigation tables (`investigations`,
`investigation_readings`, `hypotheses`, `fault_edges`,
`fault_edge_readings`), SELECT and INSERT on `narrations`, and nothing
else: it cannot write an investigation, a reading or a verification, and
cannot read a reading outside an investigation, a capture, a fact or a
user. No role holds UPDATE or DELETE on `narrations`, and triggers refuse
both, and TRUNCATE, to every role including the owner — a narration is
never rewritten; a later attempt is a new row. `api-reader` reads
`narrations` for the investigation page, and the API checks the prose
against the investigation again before it serves it. The role's URL,
`NARRATOR_DATABASE_URL`, is required by the worker even with narration
off, so turning it on is a setting, not a missing credential.

### What the narrator sends

One request per attempt, at most three attempts per investigation, made
only by the worker's `app.narrate` (no other package may reach a provider;
a `lint-imports` contract fails the build otherwise). The request carries:

- a fixed instruction (`worker/app/narrate/prompts.py`), the same for
  every investigation;
- the investigation as numbered evidence, built from its stored record and
  nothing else (`culprit_model.narration.evidence`): the symptom's subject,
  description and attestation, and the environment's name; the diagnosis's
  statement, root, recommended change and the four rubric criteria with
  their reasons; each fault edge and the reading ids that established it;
  each reading's id, probe id, target, verdict and reason; each hypothesis's
  id, kind, subject, status, reading ids and reason.

It does not carry a reading's measured values or evidence, a capture, a
configuration value, a token, telemetry, the names of users or agents, or
any tool. Everything in it was already redacted when the investigation was
stored (`redact_reading`, `redact_credentials`). A symptom description or
a reason can still say anything its writer put in it — a URL, a hostname —
and is sent as written.

| Provider | Where it goes |
|---|---|
| `none` | nowhere |
| `ollama` | `OLLAMA_URL`, the operator's own Ollama: on the same machine, nothing leaves it |
| `anthropic` | `https://api.anthropic.com/v1/messages`, with `ANTHROPIC_API_KEY`: **the evidence leaves your machine** and is handled under Anthropic's terms for API data |

**What is sent is the whole stored history, not only what comes next.**
Turning narration on narrates every investigation that has no complete
narration, newest first, three every 15 seconds. With `anthropic`, the
evidence of every investigation already stored leaves your machine, a few
at a time, until each has been narrated or has had its three attempts.

What comes back is stored only after the check, as prose, or as what it
named, or as a failure reason built from Culprit's own words — never the
provider's error text, which is not read.

## How Culprit reaches an environment

| Adapter | Reads through | Needs on the machine running Culprit |
|---|---|---|
| `compose` | `docker compose ps` and `docker inspect` | `docker`, with access to that Docker daemon |
| `kubernetes` | `kubectl get` on the Deployment, its Pods, and any ConfigMap or Secret it loads with `envFrom` | `kubectl` with a context that can `get` those. For a Secret, Culprit asks only for its **key names**, through a template that never prints its data — but Kubernetes RBAC has no "keys only" verb: a context that can `get` a Secret can read its values, so that is the access you are granting, whatever Culprit chooses to print. Withhold it and the capture says the environment was not seen whole. |
| `process` | the environment variables of the `culprit` process itself | nothing; run it where the environment's variables are |
| `exec` | a command you declare, printing NUL-delimited `KEY=VALUE` pairs (`env -0`) or a JSON object of strings — never plain lines, because a multi-line value printed line by line can pass for a variable name | that command, on the allowlist |

The adapter uses your own credentials — your Docker context, your
kubeconfig. Culprit adds no access you did not already have; it can only
narrow what it uses of it.

## The capture file

`culprit env capture production` writes a sealed envelope: the capture's
exact bytes, their SHA-256, and — with `--sign-key` — an Ed25519
signature. Inside are the facts, the grants the capture ran under, and
everything it was refused. It is safe to attach to a bug report: it
holds names and shapes, and literal values only for keys you allowlisted.

A signature proves the capture has not changed since whoever held the key
signed it. It does not prove who that was — the public key travels with
it. If that matters to you, keep a list of the key ids you trust.

`culprit diff` and `POST /captures` verify an envelope before using it:
they refuse one whose SHA-256 does not match its payload, whose signature
does not verify, or whose free text carries anything credential-shaped.
**An unsigned envelope can be edited and re-hashed by anyone**, and would
pass — the SHA-256 catches corruption, not tampering. Envelopes are
unsigned unless you pass `--sign-key`; sign them if the capture is going
anywhere you do not control, and check the key id against yours.

## The capture agent in `docker-compose.prod.yml`

An optional service, under the `agent` profile, so it never starts unless
you name it. It runs the `process` adapter with the same `.env.prod` the
api uses, so it can read the api's configuration names and shapes
without the Docker socket — mounting that socket would hand a capture
tool root on the host, for a job that needs none of it. It runs once,
prints the envelope to stdout, and exits.
