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
- **It runs once and exits.** `culprit env capture` and `culprit diff` are
  one-shot commands. There is no background agent in this release.
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
it is.

### `db.metadata.read`

**Reads:** which tables exist and which columns each has, whether each
column is nullable, and the Alembic migration version — through the
connection string in the variable `dsn_env` names, in the shell Culprit
runs in. The session is opened read-only, with a statement timeout.

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
database does not have.

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

### `model.read`, `repo.read`, `net.http.outbound`, `telemetry.logs.read`, `telemetry.metrics.read`, `telemetry.traces.read`

Named by the plan for later phases (probes, the production agent). No
code in this release uses them; granting one changes nothing and is
recorded as unused.

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
