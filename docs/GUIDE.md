# Culprit: the guide

The depth behind [the README](../README.md): every feature, how it works, the
decisions behind it, installation, a tutorial end to end, the agent surface,
testing and the project's layout. This text was the README's until Phase 40
part 2 moved it here, as it was; only its relative links were rebased from the
repository's root to `docs/`, three sentences that pointed at the README's
captures and accuracy section now link to them, and three statements that had
gone stale were corrected from their sources: the probe count, twice, and the
list of what the probes read, from the catalogue; the unverifiable surface,
from the self-check.

## Key features

| | What it lets you do |
|---|---|
| **Find contradictions before deploy** | `culprit check` extracts facts from route tables, OpenAPI specs, client call sites, ORM models, migrations, `.env.example` and dependency manifests, and reports every place two of them disagree. |
| **Know how much it matters** | Severity comes from the connection graph you declare in `culprit.yaml`: a divergence on the request path is `breaks_request_path`, one on an unread key is `cosmetic`. It is never a model's opinion. |
| **Annotate pull requests** | `--format sarif` gives GitHub pull-request annotations; JSON and JUnit are there too. Exit codes are a contract: `0` clean, `1` findings at or above `--fail-on`, `2` could not run. |
| **Compare environments safely** | `culprit env capture` reads Compose, Kubernetes or a process environment and writes a sealed, optionally signed envelope. Config values are recorded as a shape — type, length class, format — unless you grant that one key. |
| **Ask a running system** | 18 read-only probes — DNS, TCP, TLS, HTTP reachability, route and schema conformance, latency against a budget, list size, token shape and propagation, database connectivity and schema, statement budgets, plans and statements per request, config presence, installed versions, edge impedance. Each asks permission before it dials anything. Two need more than a running service to reach a verdict: config presence compares against a declaration of the key, and installed versions needs the environment to declare a `packages:` command — without one it is `refused` or `inconclusive`, and says why ([`docs/PROBES.md`](PROBES.md)). |
| **Check that a fix fixed it** | `culprit verify <investigation>` runs every probe the diagnosis ran again, twice, and compares the environment with the record of it taken at diagnosis. `verified` only when what failed now passes, what passed still passes, and nothing changed that the fix you name does not explain; otherwise `not_resolved`, `regressed`, `changed_underneath` or `inconclusive`, with the reason. From the CLI, or through the agent that diagnosed it, asked from the investigation's page, which keeps every verification. |
| **Let a coding agent ask** | `culprit mcp` serves six read-only tools over MCP on stdio — the system model, `check`, a connection explained, `probe`, `diagnose` and `verify` — each answering with the JSON its command prints. The agent proposes and applies a change; Culprit diagnoses and judges it. No argument can grant a capability, and no tool writes. |
| **Read it in words, if you want** | Optional narration: a model of your choosing — on your own machine with Ollama, or Anthropic's API — writes a short account of a finished investigation beside it, labelled as derived. It is given the investigation and nothing else, and its prose is checked against it: anything it names that the investigation does not hold, and any URL, and the prose is refused, not shown. Off by default; nothing else changes when it is off. |
| **See what was not checked** | Every gap is listed with its reason. A route table that could not be read never produces "that route does not exist" — it produces a line saying nobody looked. |

## How it works

Culprit keeps three planes of truth apart and treats disagreement between them
as the finding:

| Plane | Means | Comes from |
|---|---|---|
| **INTENT** | what the system is supposed to do | the repository: specs, route tables, migrations, `.env.example`, `culprit.yaml` invariants |
| **CONFIGURED** | what an environment is set up to do | `culprit env capture` |
| **OBSERVED** | what actually happened when measured | `culprit probe`, and the worker's impedance scoring |

Everything is a **fact** about a **subject** — `http:orders-api/GET /api/v1/orders/{}`,
`config:billing-api/BILLING_WEBHOOK_SECRET`, `schema:billing-db/public.invoices` —
with a predicate, a value, and provenance: which file, which line, which
extractor, and a confidence rank. Two independent sources that describe the
same thing produce byte-identical subjects, so comparing them is a grouping,
not a guess. The comparator knows nothing about HTTP or SQL; a new kind of
fault is a new extractor or probe, never an engine change.

A **divergence** is two facts on the same subject and predicate that disagree
(*conflict*), or a subject one source names that a source which lists
everything of that kind does not (*absence*). A **reading** is what a probe
measured, with one of four verdicts — `pass`, `fail`, `inconclusive` and
`refused` — and the INTENT fact it was compared against. `inconclusive` is a
real answer: a dropped packet does not prove a port is closed, so a timeout
never becomes `fail`.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"background": "#221331", "primaryColor": "#261537", "primaryTextColor": "#fdfdfd", "primaryBorderColor": "#7540f5", "secondaryColor": "#2f1a44", "tertiaryColor": "#180e23", "lineColor": "#ab9dbd", "textColor": "#ab9dbd", "clusterBkg": "#180e23", "clusterBorder": "#452663", "edgeLabelBackground": "#221331", "titleColor": "#fdfdfd", "fontFamily": "Inter, sans-serif"}}}%%
flowchart TB
  subgraph repo["Your repository"]
    yaml["culprit.yaml<br/>components, connections,<br/>environments, grants"]
    src["specs, route tables, call sites,<br/>ORM models, migrations,<br/>.env.example, manifests"]
  end

  subgraph cli["culprit: one static Go binary"]
    readers["built-in artefact readers"]
    plugins["extractor plugins<br/>Python and Node<br/>JSON over stdin/stdout"]
    compare["generic comparator"]
    severity["severity from the<br/>connection graph"]
    report["report<br/>text, JSON, SARIF, JUnit"]
    capture["env capture<br/>compose, kubernetes,<br/>process, exec"]
    probes["probe runner<br/>capability ledger"]
  end

  env[("a running<br/>environment")]

  src --> readers --> compare
  src --> plugins --> compare
  yaml --> severity
  capture -- "CONFIGURED facts" --> compare
  compare --> severity --> report
  compare -- "INTENT expectation" --> probes
  env -. "read under grants" .-> capture
  probes -- "read-only, under grants" --> env
  probes --> report
```

```mermaid
%%{init: {"theme": "base", "themeVariables": {"background": "#221331", "primaryColor": "#261537", "primaryTextColor": "#fdfdfd", "primaryBorderColor": "#7540f5", "secondaryColor": "#2f1a44", "tertiaryColor": "#180e23", "lineColor": "#ab9dbd", "textColor": "#ab9dbd", "clusterBkg": "#180e23", "clusterBorder": "#452663", "edgeLabelBackground": "#221331", "titleColor": "#fdfdfd", "fontFamily": "Inter, sans-serif"}}}%%
flowchart TB
  subgraph sources["Three planes"]
    intent["INTENT facts<br/>extracted from the repository"]
    configured["CONFIGURED facts<br/>captured from an environment"]
    observed["OBSERVED readings<br/>measured by a probe"]
  end

  group["group by subject and predicate<br/>http:orders-api/GET /orders/{} status_codes"]
  rank["rank picks the reference,<br/>never discards the other source"]
  div["divergence<br/>conflict or absence"]
  sev["severity<br/>breaks_request_path, degrades,<br/>cosmetic, unknown"]
  verdict["reading verdict<br/>pass, fail, inconclusive, refused"]
  out["report, with every gap listed"]

  intent --> group
  configured --> group
  group --> rank --> div --> sev --> out
  intent -- "expected_source" --> verdict
  observed --> verdict --> out
```

None of this calls a language model. Extraction, comparison, severity,
capture and probing are deterministic, and CI enforces it structurally: the
check pipeline links no networking package at all, and only the probe
package may link an HTTP client — a test lists every package under
`cli/internal` and fails on any other that links one.

### The control plane

The repository also contains a running service, the control plane. Services
push OpenTelemetry metrics and logs to an ingest gateway; a worker drains them
from Redis Streams into Postgres, flags statistical anomalies (rolling
z-score, not a model) and scores per-connection impedance, stored as probe
readings. Its API accepts the CLI's JSON (facts, captures, divergences,
readings and investigations) and stores it; the CLI itself never uploads
anything.

`culprit diagnose "<symptom>"` is the isolation walk: run where the
environment is, it walks the connection graph from the symptom, runs the
probes that discriminate between hypotheses, and prints an investigation —
a fault tree whose every edge cites the readings that established it, and a
four-part rubric (reproduced, discriminated, counterfactual, verified)
instead of a confidence score. `POST /investigations` stores one, and the
dashboard's **Investigations** page shows it: the tree with its root marked,
each edge expanding to its readings, and the hypotheses the walk did not
need kept apart from the ones it needed and could not test.

`culprit verify <investigation-id> --change config:api/DATABASE_URL` closes
the loop after someone applies a fix — Culprit verifies a change, it never
applies one. `culprit diagnose` keeps the investigation, the request behind
each reading and a capture of the environment in a local state directory;
verify measures every reading again, twice, captures the environment again
and compares the two with the engine `culprit diff` uses. A difference the
named change does not explain makes the verdict `changed_underneath`, not
`verified`. An agent does the same as a `verify` task, for the
investigations it diagnosed, and posts what it found: the investigation's
page lists every verification, newest first, and takes the rubric's
`verified` from the newest — the investigation itself is never edited. An
admin asks for one from that page, naming the change and saying whether the
fault was planted. `GET /outcomes/accuracy` counts the outcomes, per fault
class, planted apart from real; its method is [the README's](../README.md#accuracy-on-faults-we-planted).

The dashboard also pairs and manages agents (Settings → Agents), starts an
investigation through one, keeps postmortems, settings for components,
ingest keys and users, and an incident timeline that is now history: Phase 32 retired
the engine that grouped anomalies into incidents and the LLM narrative
written over them, and the incident tables are read-only. What the dashboard
does and does not do is in [`docs/LIMITS.md`](LIMITS.md).

### Narration, if you want it

An investigation's page can show a short account of it in words, written by
a language model — the one place Culprit calls one (D8). It is off by
default: with `LLM_PROVIDER=none` every command, page and journey is
complete, and the page says narration is off. It is never a finding. The
fault tree, readings and rubric on the page are; the prose restates them.

- **What the model is given.** The investigation's own record, written out
  as a numbered list of evidence — the symptom, the diagnosis and its
  recommended change, the rubric, the fault tree, each reading's probe,
  target, verdict and reason, each hypothesis. No telemetry, no tools, no
  second call. [`docs/PERMISSIONS.md`](PERMISSIONS.md) lists exactly
  what is sent.
- **What it may write.** Plain prose, citing evidence by number. Before a
  narration is stored, and again before it is shown, it is checked. Every
  citation must name an item in the list. The prose may name no subject,
  reading, probe, capability, component or code-form verdict the
  investigation does not hold, no URL, and no character outside plain
  English text. A narration that fails is stored as **refused**, with what
  it named, and the prose is not shown.
- **How it is shown.** As text: markdown and HTML appear as the characters
  they are. Each citation is replaced by its evidence item's own words,
  taken from the record rather than from the model. The page says which
  provider and model wrote it.
- **When it does not work.** A provider error, a timeout or an empty reply
  is shown as **failed**, with a reason that never repeats what the provider
  said. Three attempts per investigation, then none. Nothing is ever shown
  as pending.

Providers are set in `infra/.env.prod`, by you:

| `LLM_PROVIDER` | Also set | Where the evidence goes |
|---|---|---|
| `none` (default) | — | nowhere; nothing is narrated |
| `ollama` | `NARRATOR_MODEL` (a model you have pulled), `OLLAMA_URL` (from the worker container, `http://host.docker.internal:11434`) | a model on your own machine; no key, nothing leaves it |
| `anthropic` | `NARRATOR_MODEL`, `ANTHROPIC_API_KEY` | Anthropic's API: the evidence leaves your machine |

**Turning narration on narrates what is already stored**, not only what
comes next: every investigation without a complete narration, newest
first, three every 15 seconds, until the history is done. With `anthropic`
that means the evidence of **every stored investigation** leaves your
machine, not just the next one's. If that is not what you want, start with
`ollama`, or turn narration on in an install with no history.

The check holds identifiers, not meaning: prose can still describe the
cited evidence wrongly in plain words. That is why the evidence is shown
beside it ([`docs/LIMITS.md`](LIMITS.md), "Narration").

## Technology stack

| Role | Used |
|---|---|
| CLI and probe agent | Go 1.27, `cobra`, `yaml.v3`, `pgx` (database probes and live-schema capture). One static binary, no cgo. |
| Extractors | Python (FastAPI, Flask and Django introspection, SQLAlchemy, Alembic, `ast`), Node (`@babel/parser`) |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, `arq` jobs on Redis, managed with `uv` |
| Data | PostgreSQL 16 with TimescaleDB and pgvector, one instance, fourteen least-privilege roles |
| Ingestion | OpenTelemetry SDK in the services, a FastAPI OTLP gateway, Redis Streams |
| Anomaly scoring | `river` (EWMA mean and variance, rolling z-score) |
| Postmortem search (optional) | Voyage embeddings over the postmortem corpus |
| Frontend | React 18, Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query, visx, cmdk |
| Infrastructure | Docker Compose, Caddy, GitHub Actions, Trivy (blocking on every image) |
| Testing and checks | pytest, `go test`, `node --test`, pyright, ruff, import-linter, `tsc` in the frontend build, and the repository's own invariant checks |

## Architecture and the decisions behind it

The full reasoning is in [`docs/DIAGNOSTIC_PLAN.md`](DIAGNOSTIC_PLAN.md) §1.
In plain terms:

- **D1 — The control plane stays Python, for storage and serving.** The API,
  the worker and the database stay where they work. Comparison and severity
  moved into the Go binary instead, because `culprit check` has to run in a
  pull request with no network and no account.
- **D2 — The CLI is one Go binary.** It has to run in CI and on production
  hosts with nothing installed, so it is a static binary with no runtime.
- **D3 — Extractors are plugins in the target's own runtime.** Introspecting
  a FastAPI app means importing it, so the Python extractor runs in your
  project's environment and speaks JSON to the binary. The binary never
  parses application code.
- **D4 — Postgres is the only store.** Facts are snapshot tables, readings a
  TimescaleDB hypertable, history vectors in pgvector.
- **D5 — The undirected correlation engine is replaced, not adapted.** Faults
  propagate along directed, typed connections; an undirected graph cannot say
  which way. The anomaly scorer survives.
- **D6 — No whole-codebase model.** Culprit models interfaces — components,
  connections, contracts — not every function and import.
- **D7 — Divergence detection is generic.** All domain knowledge lives in
  extractors and probes.
- **D8 — No language model decides anything.** The one call to a model is
  the optional narrator, which turns a settled investigation into prose and
  is checked against it; it cannot create a fact, a divergence, a reading or
  a verdict, nothing reads what it writes, and `lint-imports` contracts make
  any other route to a provider a build failure.

Two standing rules come up everywhere: **a config value never appears in a
report** unless you grant that key — every report format has a test that
greps for one — and **every database role is least-privilege**: when a
component needs a write no role can do, a role is added rather than an
existing role's writes widened. Read grants are added only under the
conditions in [`.claude/rules/database.md`](../.claude/rules/database.md), and
the exceptions on record are argued there.

## Installation

### The CLI

Prerequisites: [Go 1.27+](https://go.dev/dl/), [`just`](https://github.com/casey/just),
[`uv`](https://docs.astral.sh/uv/) and [Node.js 22](https://nodejs.org/) — `uv`
and Node run the Python and Node extractors.

```bash
git clone https://github.com/Josh-Heath123/Culprit.git culprit
cd culprit
just cli-build                       # -> cli/bin/culprit
(cd extractors/node && npm ci)       # the Node extractor's one dependency
export PATH="$PWD/cli/bin:$PATH"
```

Then reproduce [the README's first capture](../README.md#see-it-work):

```bash
cd cli && culprit check -f testdata/demo/culprit.yaml
```

No release binaries are published yet; `scripts/install.sh` will download one
once there is a release to download. Until then, build from source as above.

### The control plane and dashboard (optional)

Needs only [Docker](https://docs.docker.com/get-docker/) and `just`:

```bash
just quickstart
```

This builds every image, generates every secret into `infra/.env.prod`, runs
the migrations, starts Postgres, Redis, the API, the worker and the dashboard
plus three demo services and a load generator, creates an admin account and
prints its credentials. Then it injects a fault — order-service's token for
inventory-service, re-minted for the wrong audience, so `POST /orders` fails
with a 502 — runs `culprit diagnose` inside the order-service container,
posts the investigation, and prints its address, e.g.
`http://localhost/investigations/inv-…`. Its root is
`auth:order-service->inventory-service/audience`. No API key of any kind is
needed: nothing on that path calls a model. The fault stays in place until
the next `just quickstart`; `just quickstart-down` stops everything and keeps
the data.

If it does not come up:

- **Port 80 must be free,** or set `QUICKSTART_HTTP_PORT=8088` (any free
  port) for both `just quickstart` and the address it prints.
- **Open `http://localhost`, not `http://127.0.0.1`.** Caddy serves the site
  by name; another host name gets an empty page.
- **An `infra/.env.prod` from before a schema change** lacks newer role
  passwords, and re-running the quickstart reuses it. See
  [`docs/LIMITS.md`](LIMITS.md) ("Every service now refuses to start
  without its database URL").

For a real host with a domain and TLS, follow [`docs/INSTALL.md`](INSTALL.md);
to send telemetry from your own services, [`docs/INSTRUMENTATION.md`](INSTRUMENTATION.md).

### An agent where your services run (optional)

`culprit agent` runs the same read-only probes and walk inside your network,
under grants written in its own configuration file, and takes its tasks
from the control plane over an outbound https connection — it opens no port.
Pair one from **Settings → Agents** with a single-use code, choose which of
its grants it may use (you can narrow them; nothing can widen them), and
start an investigation from the investigations page. Recipes for Docker,
Compose, Kubernetes and systemd are in [`deploy/agent/`](../deploy/agent);
[`docs/PERMISSIONS.md`](PERMISSIONS.md) lists the minimum grants for
each kind of investigation, and [`docs/SECURITY.md`](SECURITY.md) what
a compromised agent or control plane can and cannot do.

### Verifying what Culprit publishes

**Not usable yet.** The images in `ghcr.io` are private and no release has
been cut, so nothing below can be fetched by anyone but the owner today. The
commands are here so they are right on the day the packages are made public
and the first `v*` tag is pushed.

Every image and binary Culprit builds is attested where it is built: build
provenance, and for images a CycloneDX SBOM, signed through Sigstore with
the workflow run's own identity. [GitHub's CLI](https://cli.github.com/)
checks one. Name the workflow that must have signed it and the ref it must
have been built from, or a build from any workflow or branch in this
repository would pass too.

An image from `main` (`:latest`, or `:<commit>`), built by `images.yml`:

```bash
gh attestation verify oci://ghcr.io/josh-heath123/culprit/api:latest \
  --repo Josh-Heath123/Culprit \
  --signer-workflow Josh-Heath123/Culprit/.github/workflows/images.yml \
  --source-ref refs/heads/main
# Its SBOM: the same command, with --predicate-type https://cyclonedx.org/bom
```

A release's image (`:vX.Y.Z`), built by the same workflow from the tag:

```bash
gh attestation verify oci://ghcr.io/josh-heath123/culprit/api:vX.Y.Z \
  --repo Josh-Heath123/Culprit \
  --signer-workflow Josh-Heath123/Culprit/.github/workflows/images.yml \
  --source-ref refs/tags/vX.Y.Z
```

A released binary, built by `cli-release.yml` from the tag:

```bash
gh attestation verify culprit_X.Y.Z_linux_amd64 \
  --repo Josh-Heath123/Culprit \
  --signer-workflow Josh-Heath123/Culprit/.github/workflows/cli-release.yml \
  --source-ref refs/tags/vX.Y.Z
```

The images are `api`, `worker`, `frontend`, `mcp_server` and `cli`. A tag
such as `:latest` moves; to verify exactly what you run, verify it by digest
(`oci://ghcr.io/josh-heath123/culprit/api@sha256:…`).

**A pass proves** that these bytes were built by that workflow, in this
repository, from that ref, and that the record of it is in Sigstore's public
log. **It does not prove** that the code is right, that the build is
reproducible, or that whoever pushed to `main` or cut the tag meant well:
an attestation says where something came from, not that it is good. Culprit
checks the same thing itself before it publishes: each `publish` and
release run verifies what it just attested, with both flags, and fails if it
does not hold.

## Usage: one project, end to end

This is the project [the README's](../README.md#see-it-work) `diff` and `probe` captures were made from. It takes five minutes,
and step 5 three more with Docker, and needs the CLI built as above. `CULPRIT_HOME` is your clone of this
repository, so `culprit.yaml` can find the Python extractor.

```bash
# From the root of your clone. Under Git Bash on Windows, `pwd -W` gives the
# C:/... form that uv needs; everywhere else it fails and `pwd` is used.
export CULPRIT_HOME="$(pwd -W 2>/dev/null || pwd)"
mkdir -p /tmp/culprit-tour/api && cd /tmp/culprit-tour

# A service that reads three keys, and the .env.example that declares them.
cat > api/config.py <<'PY'
import os

DATABASE_URL = os.environ["DATABASE_URL"]
PAYMENTS_API_KEY = os.environ["PAYMENTS_API_KEY"]
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")
PY
printf 'DATABASE_URL=\nPAYMENTS_API_KEY=\nLOG_LEVEL=info\n' > api/.env.example

# Two routes the API says it serves.
cat > api/openapi.json <<'JSON'
{"openapi": "3.0.3", "info": {"title": "api", "version": "1"},
 "paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}},
           "/orders": {"get": {"responses": {"200": {"description": "ok"}}}}}}
JSON

# The system: web calls api on the request path, and three environments.
cat > culprit.yaml <<YAML
version: 1
components:
  - name: web
    kind: frontend
    connections:
      - to: api
        kind: http
        criticality: on_request_path
  - name: api
    kind: service
extract:
  extractors:
    - name: python
      command: ["uv", "run", "--project", "$CULPRIT_HOME/extractors/python", "culprit-extract-python"]
  components:
    api: { root: api, extractors: [python] }
environments:
  staging:
    adapter: process
    components: { api: {} }
    grants: { config.read.names: true }
  production:
    adapter: process
    components: { api: {} }
    grants: { config.read.names: true }
  local:
    adapter: process
    components: { api: {} }
    endpoints: { api: { host: 127.0.0.1, port: 8765, health_path: /health } }
    grants: { config.read.names: true, net.http.outbound: true, net.tcp.connect: true, net.dns.resolve: true }
YAML
```

**What `extract:` runs.** Every command under `extract.extractors` runs as
you, in the component's directory, whenever `culprit check`, `intent`,
`diff`, `diagnose`, `verify`, `probe` or `culprit mcp` reads INTENT — so
review a `culprit.yaml` as you would a Makefile (`--no-plugins` runs none
of them). And `culprit-extract-python` without `--no-import` is **import
mode**: it imports the project's application to read its route table, which
runs the project's own code — here, `api/config.py`, whose `KeyError` you
will see in step 1. On a project you do not control, that code can write,
connect or send anything; give the extractor `--no-import` there, which
reads the source without running it. Culprit itself writes nothing into
the project: every extractor runs with `PYTHONDONTWRITEBYTECODE=1`, so
importing leaves no `__pycache__` behind.

**1. Check the repository.** The code and `.env.example` agree, so there is
nothing to report — and the "Not checked" list says exactly what was not
looked at:

```bash
culprit check
```

**2. Capture two environments and diff them.** The `process` adapter reads
the environment `culprit` itself runs in, so each capture gets its own. It
records every variable in that environment by name and shape — never a
value — your shell's own (`SHLVL`, `OLDPWD`, `_`) included. So the tour
starts each capture from a clean environment, `env -i` with only `PATH` and
`HOME`, and the capture holds what you set and nothing the shell added:

```bash
env -i PATH="$PATH" HOME="$HOME" \
  DATABASE_URL=postgresql://app:example@db.example.internal:5432/app PAYMENTS_API_KEY=example-key LOG_LEVEL=debug \
  culprit env capture staging -o staging.capture
env -i PATH="$PATH" HOME="$HOME" \
  DATABASE_URL=postgresql://app:example@db.example.internal:5432/app LOG_LEVEL=info \
  culprit env capture production -o production.capture
culprit diff staging.capture production.capture
```

`PAYMENTS_API_KEY` is reported as `breaks_request_path`: the code reads it,
`web` reaches `api` on the request path, and production does not set it.

**3. Probe a running service.** Serve only `/health`, then ask whether each
declared route is really there (`python` rather than `python3` on Windows):

```bash
mkdir -p www && echo ok > www/health
(cd www && python3 -m http.server 8765 --bind 127.0.0.1) &
culprit probe 'http:api/GET /health' --env local -p probe.http.route_conformance --input base_url=http://127.0.0.1:8765
culprit probe 'http:api/GET /orders' --env local -p probe.http.route_conformance --input base_url=http://127.0.0.1:8765
kill %1
```

`/health` passes; `/orders` fails, because it is declared and answers 404.
Add `--format json` to see the reading's `expected_source`, which names
`api/openapi.json`.

**4. Declare a budget, and let the walk find what is slow.** Serve `/health`
400 ms slow, declare that it must answer within 300 ms at the 95th
percentile, and diagnose from inside `web`:

```bash
cat >> culprit.yaml <<'YAML'
budgets:
  - subject: "http:api/GET /health"
    predicate: latency_p95_ms
    value: 300
    why: the load balancer's health check gives up after 300 ms
YAML
cat > slow.py <<'PY'
import http.server, time

class Slow(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.4)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass

http.server.ThreadingHTTPServer(("127.0.0.1", 8765), Slow).serve_forever()
PY
python3 slow.py &
culprit diagnose web --env local --from web --no-plugins --state-dir ./state
```

Every error probe passes — `api` answers, the connection opens — so the
walk asks about latency: 50 spaced requests to `GET /health`, about 25
seconds, then 50 more to see it fail again. The diagnosis is complete:

```
Diagnosis (COMPLETE)
  root   component:api
  api is slower than the latency budget declared for it, and every component it calls on the request path keeps its own budget. The time is api's own: connection setup alone is within the budget. No latency budget a GET request can measure is declared for web, so its latency was not asked.
...
  r3   fail          probe.http.latency  http:api/GET /health
       p95 is over the 300 ms budget: at 90% confidence it is at least 402.443 ms (sample 45 of 50)
```

The same samples tell the hop from the component: connection setup alone
is within the budget, so the time is `api`'s own, not the network's. Take
the `time.sleep(0.4)` out, restart it, and — from the same shell that ran
`diagnose`, since a process capture records the shell it is launched in —
`culprit verify <id> --from web
--no-plugins --state-dir ./state --change "action:took the sleep out of
/health"` measures every reading again and says `verified`. Delete the
`budgets:` section and the same walk stays partial, saying no budget is
declared: Culprit never decides on your behalf how fast is fast. `kill %1`
when you are done.

**5. Let the walk find a missing index.** This step needs Docker and takes
about three minutes. A Postgres with `pg_stat_statements` holds a million
products in 200 categories, indexed by `sku` only. A migration in `api`
declares the same, and the storefront lists a new category that has no
products yet, five times a second:

```bash
mkdir -p api/migrations/versions
cat > api/migrations/versions/0001_products.py <<'PY'
"""The products table, listed by sku."""
import sqlalchemy as sa
from alembic import op

revision = "0001_products"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sku", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
    )
    op.create_index("ix_products_sku", "products", ["sku"])


def downgrade() -> None:
    op.drop_table("products")
PY
cat > db.yaml <<YAML
version: 1
components:
  - name: api
    kind: service
    connections:
      - to: db
        kind: sql
        criticality: background
  - name: db
    kind: database
extract:
  extractors:
    - name: python
      command: ["uv", "run", "--project", "$CULPRIT_HOME/extractors/python", "culprit-extract-python"]
  components:
    api: { root: api, extractors: [python] }
budgets:
  - subject: "schema:db/public.products"
    predicate: query_mean_ms_max
    value: 20
    why: the product list reads the first page of one category
environments:
  shop:
    adapter: process
    components:
      api: { database: { dsn_env: SHOP_DB_DSN } }
    grants: { config.read.names: true, db.stats.read: true, db.plan.read: true }
YAML
docker run -d --name culprit-tour-db -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=tour \
  postgres:16-alpine -c shared_preload_libraries=pg_stat_statements
until docker exec culprit-tour-db pg_isready -q -h 127.0.0.1 -U postgres; do sleep 1; done
docker exec -i culprit-tour-db psql -q -U postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION pg_stat_statements;
CREATE TABLE products (id serial PRIMARY KEY, sku text NOT NULL, category text NOT NULL);
CREATE INDEX ix_products_sku ON products (sku);
INSERT INTO products (sku, category)
  SELECT format('sku-%s', lpad(i::text, 7, '0')), format('category-%s', i % 200)
  FROM generate_series(1, 1000000) AS i;
ANALYZE products;
CREATE ROLE culprit_reader LOGIN PASSWORD 'reader' IN ROLE pg_read_all_stats;
GRANT SELECT ON products TO culprit_reader;
SQL
docker exec -i culprit-tour-db sh -c 'cat > /tmp/list.sql' <<'SQL'
SELECT sku FROM products WHERE category = 'category-new' ORDER BY sku LIMIT 50;
SQL
docker exec -d culprit-tour-db sh -c 'pgbench -n -U postgres -f /tmp/list.sql -R 5 -T 900 postgres'
export SHOP_DB_DSN=postgresql://culprit_reader:reader@127.0.0.1:55432/postgres
export DATABASE_URL=postgresql://app:example@db.example.internal:5432/app PAYMENTS_API_KEY=example-key
culprit diagnose api --env shop -f db.yaml --from api --state-dir ./state
```

Culprit reads the database as `culprit_reader`, which can read statistics
and plan a statement, and never sees a row. It never runs your statements
and makes no traffic: it times the statements the traffic already runs over
a 30-second window, then reads the generic plan of the one over its budget,
without executing it:

```
Diagnosis (COMPLETE)
  root   schema:db/public.products.category
  api is slow because a statement on table products in database db is over the statement budget declared for it, and no index serves category: the plan filters category row by row on public.products, with no index condition serving it, and it walks ix_products_sku for its order. No live index leads category, and the migrations declare none. ...
  fix    Add an index on public.products (category, sku): the columns the plan filters, then those of the index it walks for its order. Verification, not this recommendation, decides whether a change worked.
...
  r3   fail          probe.db.statement_budget  component:db
       statement 4650866916234037515 is over its 20 ms budget: 18364131 µs over 150 call(s) in the window, more than 20 ms each
```

The root needs four planes to agree:

- the statement is over its budget;
- the plan filters `category` row by row;
- no live index leads `category`;
- the migrations declare none.

A seeded category would be fast: the walk along `sku` finds 50 matches
within about 10,000 entries and stops. Only a category with no products
makes it walk the whole index (`docs/LIMITS.md`). To fix it, add the index
as a migration, apply it, and verify, giving `culprit verify` the
investigation id that `diagnose` printed:

```bash
cat > api/migrations/versions/0002_products_category_sku.py <<'PY'
"""Index products by category, then sku."""
from alembic import op

revision = "0002_products_category_sku"
down_revision = "0001_products"


def upgrade() -> None:
    op.create_index("ix_products_category_sku", "products", ["category", "sku"])


def downgrade() -> None:
    op.drop_index("ix_products_category_sku", table_name="products")
PY
docker exec culprit-tour-db psql -q -U postgres -c "CREATE INDEX ix_products_category_sku ON products (category, sku)"
culprit verify <id> -f db.yaml --from api --state-dir ./state \
  --change "action:added and applied migration 0002, an index on products (category, sku)"
```

The statement is measured again, twice, and passes both times: `Verdict
(VERIFIED)`. An index on `category` alone would leave this read where it
was, because the planner does not use it for a category it expects to be
as common as any other; the fault library checks that verification says
`not_resolved` for exactly that fix. `docker rm -f culprit-tour-db` when
you are done.

**On your own repository:** describe your components and connections in
`culprit.yaml` (the demo's [`cli/testdata/demo/culprit.yaml`](../cli/testdata/demo/culprit.yaml)
is a fuller example, with route, schema and client-call extraction), then run
`culprit check` in CI with `--format sarif`. The tour runs the Python
extractor from Culprit's own environment because its one file imports
nothing; for a real application the extractor has to import your code, so
install it into your project's environment instead
([`extractors/python`](../extractors/python/README.md),
[`extractors/node`](../extractors/node/README.md)). `culprit.yaml` names config
keys and never their values, and the loader refuses anything that looks like
a credential.

**Latency budgets.** How fast a route must be is something you declare,
never something Culprit guesses from history. A budget is an INTENT fact:

```yaml
budgets:
  - subject: "http:api/GET /orders"
    predicate: latency_p95_ms      # or latency_p50_ms
    value: 300                     # whole milliseconds
    why: the order list page waits on it
```

or `x-culprit-budget: { latency_p95_ms: 300 }` on an OpenAPI operation.
`culprit check` reports two sources that disagree as an `intent_conflict`,
lists a budget whose route nothing else declares, and, once you declare
any, lists the routes that have none. `probe.http.latency` measures a
route against its budget ([`docs/PROBES.md`](PROBES.md)), and
`culprit diagnose` uses it once the errors explain nothing (step 4 above);
its limits are in [`docs/LIMITS.md`](LIMITS.md), "Latency budgets".

**Bundle budgets.** How much a page may download is declared the same
way. Point `culprit check` at your Vite build's manifest and budget an
entry in gzipped bytes:

```yaml
components:
  - name: web
    kind: frontend
    build:
      vite_manifest: web/dist/.vite/manifest.json   # build.manifest: true in vite.config
budgets:
  - subject: "bundle:web/index.html"
    predicate: bundle_gzip_bytes_max
    value: 200000                    # whole bytes, gzipped
    why: the first page waits on it
```

Build before you check, in the same CI job:

```yaml
- run: cd web && npm ci && npm run build
- run: culprit check --fail-on=degrades --format sarif --output culprit.sarif
```

An entry over its budget is a `degrades` finding naming its three largest
files. What counts is the entry's first load: its own chunk, what it
statically imports and their CSS, not what `import()` loads later. With no
build present the budget is listed as "Not checked", which does not by
itself fail `--fail-on`: if your CI must judge it, fail on that line too.
Culprit's own CI holds its dashboard to 200,000 bytes this way, and fails
if the budget goes unjudged (the root `culprit.yaml`, and the self-check
job); the limits are in [`docs/LIMITS.md`](LIMITS.md), "Bundle
budgets".

**List budgets.** How many items a route may answer is declared too, and
only declared: Culprit never infers a bound from a parameter's name. A
bound is `maxItems` on the list in your OpenAPI spec, or a budget, with
`at:` pointing at the list when the response wraps it:

```yaml
budgets:
  - subject: "http:inventory-service/GET /products"
    predicate: response_items_max
    value: 50                        # whole items
    at: /products                    # a JSON pointer; leave it out for a top-level array
    why: the storefront shows one page
```

Both OpenAPI readers (a committed spec, and your running FastAPI app's
`app.openapi()`) record each route's list: a 2xx JSON response that is an
array, or an object with exactly one array property. Once you declare any
budget, `culprit check` lists the **unbounded surface** beside the
unbudgeted one: list routes with no `maxItems` and no `response_items_max`.
It is a list to read, never a finding. `probe.http.response_items` sends
one GET, with no query and no credential, and counts the list: over the
bound fails, within it passes, and a response it cannot count (not 2xx,
not JSON, no array at `at:`) is inconclusive and says why. It keeps the
count, never an item. On the demo:

```bash
culprit probe "http:inventory-service/GET /products" -p probe.http.response_items \
  --input base_url=http://inventory-service:8002 -f demo-services/culprit.yaml --env faults
```

The fault library runs exactly this in CI, inside the faults stack, and
it passes: the probe asks for the default page, of the storefront's
featured category, which is empty by design (step 5). Its output there
(CI run 44180363288, copied from the log):

```text
PASSING (1)
  probe.http.response_items  http:inventory-service/GET /products
      measured: at=/products items=0 method=GET status=200 url=http://inventory-service:8002/products

0 failing, 0 inconclusive, 0 refused, 1 passing
```

The limits are in [`docs/LIMITS.md`](LIMITS.md), "List budgets".

**Databases.** A component's database is reached through a variable you
name, never a connection string in the file:

```yaml
environments:
  production:
    grants: { db.metadata.read: true }
    components:
      orders-api:
        database: { dsn_env: ORDERS_DATABASE_URL }
```

Under `db.metadata.read`, `culprit env capture` and `culprit diff` read
the live schema — tables, columns, nullability, the migration version and
which columns lead an index — through a read-only session that can send
only a fixed set of catalogue statements, and compare it with what your
Alembic migrations declare: a missing migration, or an index the
migrations declare and the database lacks (or the reverse), is a finding.
Under `db.stats.read`, `probe.db.statement_budget` times each statement
over a 30-second window of the system's own traffic against a
`query_mean_ms_max` budget; under `db.plan.read`, `probe.db.plan` reads the
generic plan of one statement, never running it. When the errors and the
latency explain nothing below the symptom, `culprit diagnose` asks the
databases the entry connects to, and roots at a missing index only when the
statement, the plan, the live indexes and your migrations all agree,
recommending the index the plan needs
([`docs/PROBES.md`](PROBES.md), "In the walk").
[`docs/PERMISSIONS.md`](PERMISSIONS.md) says what each grant reads and
what role it needs.

**N+1, where it can be seen cleanly.** A list route that runs one statement
per item it returns is found only in an environment you declare
`isolated: true`, where nothing but Culprit talks to the database while it
measures, and only beneath a route over its declared latency budget. There
`culprit diagnose` brackets one `GET` of the slow route with
`pg_stat_statements` snapshots and counts the list's items from the same
response: a statement called at least once per item is the N+1. In any
other environment it is not asked, and the diagnosis says so in one
sentence. The fault library plants one on the demo's `GET /products/details`
(`N_PLUS_ONE_FAULT=details-per-product`, a page of 500). This is that walk,
from CI's log (run 44333504867):

```
Symptom    http:inventory-service/GET /products/details
           GET http://inventory-service:8002/products/details
           reproduced read-only (r2)
Environment faults-inventory-isolated   investigation inv-44e702ec65e944b9

Diagnosis (COMPLETE)
  root   http:inventory-service/GET /products/details
  inventory-service is slow because GET /products/details on inventory-service runs one statement per item it returns: statement 8878744738955718652 (SELECT description, weight_grams FROM product_details WHERE product_id = $1) ran 500 times for the 500 items one request returned. The route is over the latency budget declared for it, and nothing it calls on the request path is slow.
  fix    Load the relation for every item in one statement, a join or one query over the items' keys, in place of statement 8878744738955718652 (SELECT description, weight_grams FROM product_details WHERE product_id = $1) run once per item. Verification, not this recommendation, decides whether a change worked.

Confidence — four checks, never a number
  reproduced      yes  probe.http.latency failed again when run a second time (r2, then r4)
  discriminated   no   no reading ruled out a competing explanation
  counterfactual  no   no reference environment was named (--reference)
  verified        no   not yet verified: after a fix is applied, `culprit verify inv-44e702ec65e944b9 --change ...` measures every reading again and compares the environment with the record of it taken at diagnosis

Fault tree — every edge cites the readings that established it
  http:inventory-service/GET /products/details
    -[symptom_of]-> component:inventory-service   (r2)
  component:inventory-service
    -[caused_by]-> http:inventory-service/GET /products/details   (r3, r2)

Supported (2)
  latency_budget_exceeded  component:inventory-service  (r1, r2)
  n_plus_one               http:inventory-service/GET /products/details  (r3, r2)

Untested — the walk did not need them; neither ruled out nor in (1)
  component_fails          component:inventory-service

Readings
  r1   pass          probe.http.latency  http:inventory-service/GET /products
       p95 is within the 25 ms budget: at 90% confidence it is at most 4.855 ms (sample 50 of 50)
  r2   fail          probe.http.latency  http:inventory-service/GET /products/details
       p95 is over the 25 ms budget: at 90% confidence it is at least 143.653 ms (sample 45 of 50)
  r3   pass          probe.db.statements_per_request  http:inventory-service/GET /products/details
       1 statement(s) ran at least once per item of 500: 8878744738955718652 (500 calls)
  r4   fail          probe.http.latency  http:inventory-service/GET /products/details
       p95 is over the 25 ms budget: at 90% confidence it is at least 140.837 ms (sample 45 of 50)
```

With the join restored, `culprit verify` measures every reading again and
says `verified`, adding that the statement no longer runs once per item.
The route's cost is the machine's round trip to the database, so its budget
is set from CI's spread ([`docs/LIMITS.md`](LIMITS.md), "N+1 in the
walk").

### For a coding agent: `culprit mcp`

A coding agent that speaks MCP can start the binary as a tool server and run
the loop itself — diagnose, change something, verify:

```json
{
  "mcpServers": {
    "culprit": {
      "command": "culprit",
      "args": ["mcp", "-f", "/path/to/culprit.yaml", "--from", "order-service"]
    }
  }
}
```

| Tool | What it answers |
|---|---|
| `culprit_system_model` | components, connections, each environment's adapter and grants, this server's vantage |
| `culprit_check` | `culprit check --format json` |
| `culprit_explain_connection` | the facts and contradictions about one connection, and which probes can measure it under an environment's grants |
| `culprit_probe` | `culprit probe --format json`, for named probes, at endpoints the environment declares |
| `culprit_diagnose` | the investigation `culprit diagnose --format json` prints, and the `culprit_verify` call that checks a fix |
| `culprit_verify` | the verification `culprit verify --format json` prints |

What it cannot do: grant itself anything — grants are the environment's, in
`culprit.yaml`, fixed when the server starts (an edit to the file refuses every
later call until it is restarted), an argument that names one is refused, and a
probe the environment does not grant is refused before anything is sent; send a
probe anywhere `culprit.yaml` does not declare — a `url`, `base_url`, `host` or
`port` that is not one of the environment's endpoints is refused, nothing
dialled (from a terminal, `culprit probe` still goes where its inputs say); choose where it
runs — `--from` and the state directory are the server's, set when it starts;
or change anything — no tool writes to `culprit.yaml`, an environment or the
control plane, and Culprit never applies a fix. It speaks stdio only, calls no
model, and its answers carry no prose. Run it where `culprit diagnose` would
run: probes see what their vantage sees ([`docs/LIMITS.md`](LIMITS.md),
"The agent surface").

## Testing

| Command | Covers |
|---|---|
| `just test` | everything below that needs no cluster: the api, worker and MCP server suites (with the repository's own scripts and the shared model's conformance tests), `go test` across the CLI, and both extractors. Needs Docker for Postgres |
| `just cli-test` | every Go package: extraction, the comparator, severity, every report format, capture, all 18 probes, and the eval suites in `cli/testdata/faults` and `cli/testdata/envdiff`, which assert the exact divergence set with zero false positives |
| `just extractors-test` | the Python and Node extractors |
| `just self-check` | `culprit check` on this repository, failing on `degrades`: **no divergences, 1,766 facts across 633 subjects**, 9 gaps listed, and the dashboard's first load within its 200,000-byte gzip budget (run `just frontend-build` first, or the budget is "Not checked") |
| `just self-check-coverage` | the 535 subjects only one source describes — places where a mistake would go uncaught |
| `just cli-test-docker`, `just cli-test-kind` | environment capture against real Compose projects and a kind cluster |
| `just check-migration-round-trip` | every migration upgrades, downgrades and upgrades again against a real database with rows in it |
| `just lint`, `just typecheck`, `just lint-imports` | ruff and `gofmt`/`go vet`, pyright, and the import contracts that keep the deterministic packages away from any LLM client |
| `just e2e` | the dashboard in a real browser (Playwright) against a running `just quickstart`: sign in, read a complete and a partial investigation, keyboard alone, every route at 375, 768, 1280 and 1920 px, the settings journeys, and a deliberate error path — any console error or failed request elsewhere fails it |
| `cd frontend && npm test` | the dashboard's unit tests (Node's own runner): the one date format, the hypothesis labels, flags in prose |
| `just check-frontend-tokens` | no page styles itself outside the design tokens; `scripts/tests/test_design_tokens.py` measures every text token on every surface, each status colour on its own tint, and white on the blue fill, against WCAG 2.2 AA (4.5:1) |

CI runs every row on every pull request except `just self-check-coverage`,
whose report it prints in the self-check job's log without ever failing on
it. It also builds every image and scans each with Trivy, failing on any
HIGH or CRITICAL finding that has a fix available. Findings with no fix
available are left out of the scan's output altogether (`ignore-unfixed`),
so they are neither blocking nor visible there.

Getting the self-check to zero honestly meant fixing the tool rather than the
repository more than once. And an earlier version printed **484 facts** and
also said zero, because the FastAPI route table and the ORM had
failed to extract and nobody noticed that "no findings" meant "nothing
looked". That is the failure this tool exists to prevent, caught in its own
dogfooding, and it is why the "Not checked" list is never optional.

## Project structure

| Path | What it is |
|---|---|
| [`cli/`](../cli) | the Go binary: `check`, `intent`, `env capture`, `diff`, `probe`, `diagnose`, `verify`, `agent`, `mcp` |
| [`extractors/`](../extractors) | the Python and Node extractor plugins ([protocol](EXTRACTOR_PROTOCOL.md)) |
| [`shared/`](../shared) | the core model — planes, facts, subjects, readings — shared by the Python services |
| [`api/`](../api) | FastAPI: the dashboard's API, the ingest gateway, capture and reading endpoints, migrations |
| [`worker/`](../worker) | arq jobs: stream draining, anomaly and impedance scoring, postmortem embedding, narration (optional) |
| [`frontend/`](../frontend) | the React dashboard |
| [`mcp_server/`](../mcp_server) | read-only MCP tools over Culprit's engineering memory, for coding agents (the diagnostic tools are `culprit mcp`, in the binary) |
| [`demo-services/`](../demo-services) | three small instrumented services the quickstart runs |
| [`infra/`](../infra) | Compose files, Caddy, deployment |
| [`deploy/agent/`](../deploy/agent) | the agent's recipes: Docker, Compose, Kubernetes, systemd |
| [`scripts/`](../scripts) | the repository's own invariant checks, bootstrap and capture tooling |
| [`docs/`](../docs) | the plan, limits, permissions, probes, install and upgrade guides |

## Limits

Culprit states its limits rather than implying it has none:
[`docs/LIMITS.md`](LIMITS.md) covers every threshold, heuristic and
coverage gap, from what an extractor cannot see to why a timeout is never a
failure. [`docs/PROBES.md`](PROBES.md) documents each probe and
[`docs/PERMISSIONS.md`](PERMISSIONS.md) every grant.
