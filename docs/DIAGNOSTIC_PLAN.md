# Culprit — Diagnostic Engine Plan (Phases 26–35)

Written 2026-09-08. Companion to, and successor of, `docs/IMPLEMENTATION_PLAN.md`
(Phases 0–12), `docs/SELF_HOSTED_PLAN.md` (Phases 13–20) and
`docs/AI_NATIVE_PLAN.md` (Phases 21–25). Same convention as those documents:
read §1 (invariants) plus the specific phase section you are working on, not
the whole file.

**Phase 25 (memory visualisation) is cancelled.** It was never built and the
new direction supersedes it. Do not implement it.

**Three phases were inserted on 2026-11-03.** Phase 31.1 closes Phase 31's
probe loop. Phases 31.2 and 32.1 fold in the productisation brief
(`docs/PRODUCTISATION.md`): 31.2 presents what already works, before Phase 32;
32.1 builds the design system and the interface around investigations, after
it. The order is 31 → 31.1 → 31.2 → 32 → 32.1 → 33 → 34 → 35.

**This plan evolves the existing repository. There is no new repository.**
Every phase below names the existing files it modifies. Where something is
removed, the reason is stated; nothing is removed merely because the product
direction changed, and nothing is preserved merely because it exists.

---

## §0. Read this first — where the vision needs correcting

The product direction is sound and the analogy holds. Five things in it will
produce a bad product if implemented literally. Each is stated here with the
correction that the rest of this plan assumes.

### §0.1 "Deviation from correct" is three problems, not one — and one of them is impossible

The vision lists these as one class:

- an API consistently returns the wrong data
- a frontend consistently calls the wrong endpoint
- an auth configuration consistently uses the wrong audience
- a database query consistently produces an incorrect result
- a service consistently sends malformed data to another service
- a deployment consistently uses an incorrect environment variable
- **a business rule is implemented incorrectly but produces perfectly stable behaviour**

They are not one class. They divide by *what makes them decidable*:

**Tier 1 — structural incorrectness. Decidable, deterministic, high value.**
Wrong endpoint, wrong audience, malformed payload, wrong environment variable.
In every case the system contains **two representations of the same intent that
can be mechanically compared**: the frontend's call sites and the server's route
table; the token's `aud` claim and the verifier's expected audience; the payload
shape and the declared schema; the required variable and the present variable.
This is where Culprit lives. It is decidable without running anything, and being
wrong is checkable.

**Tier 2 — semantic incorrectness against a declared expectation. Decidable only
where a declaration exists.** "Returns the wrong data" is decidable if and only
if something in the system declares what the right data is: a test assertion, a
type constraint, a database `CHECK`, a schema `required`, an explicit invariant.
Culprit can find those declarations and check conformance. It cannot invent them.

**Tier 3 — business-rule incorrectness. Not decidable. Do not promise it.**
If the code says `discount = price * 0.9` and the business wanted `0.85`, nothing
in the system knows. No probe, no static analysis, no LLM finds this, because the
intent exists in exactly one place and that place is the bug. Any roadmap that
promises Tier 3 fails its own standard on first contact with a real user.

**Correction.** The product claim is: *Culprit detects incorrectness wherever the
system contains two representations of the same intent that can be compared.*
That is a strong, honest, defensible claim, and it covers the large majority of
integration and environment faults.

There is a valuable corollary that falls straight out of this and should be built
(Phase 29): Culprit can report **where your system has un-cross-checkable
intent** — a route with no test and no spec, a config key read in one place and
declared nowhere, a business rule with no assertion anywhere near it. "Here are
the 34 places in your system where nothing could ever catch a mistake" is a real,
shippable, genuinely useful feature, and it is honest about Tier 3 rather than
pretending to solve it.

### §0.2 Four kinds of behaviour is one too many

The vision names four: Observed, Expected, Historically normal, Declared.
"Expected" and "Declared" are not operationally distinct — expected behaviour
*is* whatever is declared somewhere. Keeping both invites an "expected" plane
with no source, which is exactly where hand-waving lives.

And **historically normal is not a plane.** It is a statistic derived from
observed data. Promoting it to a plane is precisely the mistake the current
architecture already makes: treating "usual" as a proxy for "correct".

**Correction — three planes and one derived statistic:**

| | What it is | Where it comes from |
|---|---|---|
| `INTENT` | What the system is supposed to do | Specs, schemas, types, migrations, tests, config declarations, explicit assertions |
| `CONFIGURED` | What a specific environment is actually set up to do | Env vars, live DDL, DNS, image digests, IAM, installed versions |
| `OBSERVED` | What actually happened or was measured | Traces, logs, metrics, probe readings |
| *baseline* | Derived statistics over `OBSERVED` | Never a source of truth; ranks hypotheses only |

Every finding is a **divergence between two planes**, or between the same plane
in two environments. That is the whole engine.

### §0.3 Intent sources will disagree — and that must be a finding, not a resolution step

The vision is right that sources conflict and that this matters. The design
consequence is stronger than the vision states: **an intent conflict is itself a
bug, usually a serious one, detectable before deployment.** If `openapi.json`
says `/api/v2/users` and the route decorator says `/api/v1/users`, that is not
ambiguity to be resolved by picking the more trustworthy source — it is a
finding to report.

**Correction.** Intent sources carry an explicit `confidence_rank` (§2.4). Rank
is used to *order the report* and to pick a default when a comparison needs one.
Rank is **never** used to silently discard the losing source. Disagreement emits
a `intent_conflict` divergence.

### §0.4 "Controlled active probes" in production needs a structural boundary, not a config flag

An active probe does something to the running system. A synthetic
`POST /orders` creates an order. If this is a settings toggle, it will
eventually be on when it should not be, and Culprit will have written to a
customer's production database. That ends the product.

**Correction — the boundary is in the capability grant, not the probe.** Probes
declare an `effect` class in their manifest (`inspect` / `observe` /
`interrogate` / `mutate`). **No `mutate` probe exists in the core catalogue, and
manifest validation rejects `effect: mutate` outright in every phase of this
plan.** The agent is not given credentials that permit writes, so a probe that
tried to mutate could not succeed even if one existed. Synthetic transactions
against write endpoints are out of scope for this entire plan (§4).

Related, and equally hard: **database metadata, never database rows.** Schema,
constraints, indexes, migration version, connection counts, lock waits — yes.
Row contents — no, by default and by capability. Row reads require an explicit
per-table grant and are redacted by default. Get this wrong once and the product
is a compliance non-starter for exactly the small teams it targets.

### §0.5 Static analysis of large polyglot codebases is how this project dies

"Useful on 300k-line codebases" plus "derive expected behaviour from source
code" reads as: build language-aware static analysis for Python, TypeScript, Go
and Java. That is a multi-year effort and it is the most likely single cause of
this project never shipping.

**Correction — a strict source preference order. Parse artefacts, not code:**

1. **Machine-readable declarations that already exist.** OpenAPI/AsyncAPI, JSON
   Schema, GraphQL SDL, protobuf, Alembic/Prisma/Django migrations, lockfiles,
   Terraform state, Kubernetes manifests, `.env.example`, compose files. Free,
   exact, language-agnostic.
2. **Runtime introspection over static parsing.** A FastAPI app can emit its own
   route table via `app.openapi()`. Django emits its URLconf. Express can be
   walked. **Ask the application what it exposes rather than parsing the code
   that builds it** — dramatically more accurate, and roughly 5% of the work.
3. **Thin, optional, language-specific extractors** — only for what the first two
   cannot give. In practice that is chiefly *client call sites* (frontend
   `fetch`/`axios` URLs). Use tree-sitter with a small query set. Not type-aware
   analysis. Not a code property graph.

This ordering is a hard architectural rule (D6, §1.6), and it also resolves the
stack question — see D3.

---

## §1. Architectural decisions

Each decision states the choice, the alternatives, the trade-off, the assumption
it rests on, and what would cause us to revisit it.

### D1 — The control plane stays Python

**Chosen.** `api/` and `worker/` remain Python/FastAPI/SQLAlchemy/Alembic/arq.
All analysis, storage, correlation and the web API stay where they are.

**Alternatives.** Rewrite in Go for a single-language codebase; rewrite in
TypeScript for frontend/backend symmetry.

**Why.** It is built, tested, deployed, and the ecosystem is right for this
domain (SQLAlchemy, Alembic, pydantic, OTel SDK, tree-sitter bindings). A rewrite
buys nothing the product needs and costs the entire remaining runway. The
reconnaissance found the engineering standard here to be high; that is capital,
not sunk cost.

**Trade-off.** Python is a poor distribution story for a CLI. D2 handles that.

**Revisit if.** The control plane becomes CPU-bound on graph traversal at a scale
where PyPy/Rust extensions are insufficient — unlikely before thousands of
components.

**Amended 2026-11-03 — where analysis actually lives.** The choice above says
all analysis stays in Python. The plan's own Phase 29 moved comparison and
severity into the Go binary, deliberately, because `culprit check` must work in
a pull request with no account and no network; Phase 32 puts the isolation walk
there too. Checked 2026-11-03: no comparison, severity or isolation logic exists
in Python — `api/`, `worker/` and `shared/` carry the divergence kinds as enums
and nothing more. So D1 stands for storage and serving, and the boundary that
actually holds is:

- **Go (`cli/`)** — everything that runs where the developer, the CI job or the
  agent is: extraction orchestration and the artefact readers, environment
  capture, comparison, severity, probes, and isolation.
- **Python (`api/`, `worker/`)** — everything that persists, serves or
  aggregates over time: storage, the HTTP API, auth, the dashboard's backend,
  telemetry ingest, the anomaly scorer and the narrator.
- **Both** — the model (`Fact`, `Reading`, subject URIs), held together by
  conformance fixtures that both languages read. This is the only logic
  permitted to exist twice.

D2's revisit triggers police this boundary.

### D2 — The CLI and the probe agent are a single Go binary

**Chosen.** A new top-level `cli/` module, written in Go, producing one static
binary `culprit` that serves as both the developer CLI and the deployable probe
agent (same binary, different subcommand).

**Alternatives.** (a) Python CLI shipped via `pipx` or a container. (b) Rust.
(c) Node.

**Why.** The single most important adoption moment is a developer running one
command in their CI or terminal. `pip install` into an unknown Python, or
`docker run` with volume mounts, is friction at exactly the wrong moment. Go
gives a ~15 MB static binary, `curl | sh` installation, trivial cross-compilation,
a scratch-based container for the agent, and a standard library that covers
almost exactly what a probe does: DNS, TCP, TLS, HTTP, process execution,
filesystem, concurrency. Rust would also work and is slower to write; Node
reintroduces a runtime dependency.

**Trade-off — stated plainly.** Two languages in one repository raises the
maintenance floor for a small team. This is a real cost. It is accepted because
the agent is small (single-digit thousands of lines), changes slowly, and sits
behind a narrow versioned JSON contract (D3), which also means it could be
replaced later without touching the control plane.

**Assumption.** The author is willing to learn enough Go to maintain a
network-and-process tool. If not, the fallback is a Python CLI distributed as a
single file via PyInstaller — worse, but not fatal; make that call before Phase 28
rather than midway through it.

**Revisit if.** By the end of Phase 29 the Go surface has grown past ~6k lines or
is absorbing logic that belongs in the control plane. That is a signal the
boundary is wrong, not that the language is.

**Amended 2026-11-03 — the size trigger is retired.** The trigger above fired
long ago: the Go surface was 13,496 non-test lines at Phase 31, against ~6k.
Line count was a weak proxy. The surface grew because the analysis engine lives
in Go (D1, amended), not because control-plane logic leaked into it. The
trade-off paragraph's premise — a small agent that changes slowly — is no
longer true and should not be relied on: the Go side is the core of the
product, and its maintenance cost is the real cost of this decision.
**Revisit if, instead:**

1. any logic other than the shared model is implemented in both languages —
   the boundary is in the wrong place, and one side must go;
2. the binary gains persistent storage or a listening server (the agent is
   outbound-only, Phase 33);
3. Python gains probe execution, a second comparator or a second isolation
   walk — the likeliest route being a dashboard-initiated investigation
   (Phase 32, "Added 2026-11-03").

### D3 — Intent extractors are subprocess plugins running in the target's own runtime

**Chosen.** An extractor is any executable that accepts a JSON request on stdin
and emits `Fact` objects as JSON on stdout, conforming to a versioned schema.
The `culprit` binary orchestrates; it never parses application code itself.

Shipped extractors:
- `culprit-extract-python` — a small Python package the user installs in the
  project's own virtualenv. Introspects FastAPI/Flask/Django route tables,
  SQLAlchemy metadata, Alembic head, pydantic models, `os.environ` access sites.
- `culprit-extract-node` — an npm package. Route definitions, and client call
  sites via tree-sitter.
- Built-in artefact readers (in Go, no plugin needed) — OpenAPI, JSON Schema,
  `.env.example`, compose/k8s YAML, lockfiles, Terraform state.

**Why this is the right factoring and not just a convenience.** Introspecting a
FastAPI app requires importing it, which requires that project's virtualenv and
its dependencies. No external process can do this correctly. Accepting that up
front turns the polyglot problem from "we must write a static analyser per
language" into "each ecosystem contributes a small extractor in its own
language" — which is also the extension point third parties can use.

**Alternatives.** A single Go static analyser using tree-sitter for every
language (inaccurate for anything involving dynamic route registration, which is
most frameworks); an LSP-based approach (heavy, and language servers are not
designed to answer these questions).

**Import-time environment: synthetic only, never the user's real values.**
(Resolves Q8, 2026-09-09.) Importing an application to introspect it often
requires environment variables to be set. `culprit.yaml`'s `extract:` section
declares which *names* must be present; the CLI generates **synthetic values that
satisfy the shape** (`postgresql://extract:extract@localhost/extract`) and passes
those. It never sources the user's `.env`, and there is no option to.

The reason is Phase 28's own defect chain (standing invariant 11): every error
path is an exfiltration path, so the only safe extractor process is one that
never held a real credential in the first place. If an application genuinely
cannot be imported without a live connection, the extractor emits `skipped` with
that reason — an honest partial answer, which is the whole design of the
protocol.

**Trade-off.** Extraction requires installing something into the user's project.
Mitigation: it is one dev-dependency, it is pure-Python/pure-JS, it imports
nothing at runtime, and `culprit check` degrades to artefact-only extraction if
it is absent — with a `refused`-style note saying which facts could not be
gathered and why.

**Revisit if.** Runtime introspection proves unreliable across framework versions
often enough that maintaining extractors costs more than static parsing would.

### D4 — Postgres remains the single store; readings become a hypertable

**Chosen.** `intent_facts` and `configured_facts` are snapshot tables versioned
by capture id. `readings` is a TimescaleDB hypertable, the same treatment
`raw_events` already has. `divergences`, `investigations`, `fault_edges` are
ordinary relational tables. pgvector stays for the historical corpus.

**Why.** One store, already provisioned, already has Timescale and pgvector, and
the existing least-privilege role model extends to new tables cleanly. Nothing
about this workload needs a graph database — the system model is small (hundreds
of nodes, not millions) and traversal happens in memory.

**Revisit if.** A single system model exceeds ~50k components/connections, or
traversal queries become the bottleneck.

### D5 — The undirected correlation engine is replaced, not adapted; the anomaly scorer survives with a new job

**Chosen.** `worker/app/correlation/graph.py` is removed in Phase 32. Its central
data structure is `nx.Graph` — undirected — and the new engine needs direction,
edge types and contracts. This cannot be adapted; the structure is the problem.

`worker/app/anomaly/` **survives**, re-sited: it stops producing "incidents" and
starts producing *impedance readings per connection* — the `OBSERVED`-plane
answer to "deviation from usual", which the vision correctly keeps as one of the
two questions. The EWMA scorer, its Redis state, and its tests are all reusable
as-is; only its consumer changes.

**Trade-off.** Roughly 350 lines of tested correlation code is deleted. Accepted;
the tests documenting its semantics are deleted with it.

### D6 — No whole-codebase semantic model, ever

**Chosen.** Culprit models the system's *interfaces* — components, connections,
contracts. It does not model the codebase's internals: no file/function/import
graph, no code property graph, no "understand the whole repository".

**Why.** `docs/AI_NATIVE_PLAN.md` already argued this correctly against the
CodeSee precedent, and the reasoning is unchanged. It is also unbounded work with
no natural stopping point, and it is not what diagnosis needs — a fault at the
integration layer is found by comparing interfaces, not by understanding
implementations.

**Revisit if.** Never, within this plan. If it seems necessary, the actual need is
almost certainly a more specific extractor.

### D7 — Divergence detection is generic; all domain knowledge lives in extractors and probes

**Chosen.** The comparator knows nothing about HTTP, SQL or auth. It compares
`Fact` objects that share a `subject` and `predicate` (§2.2). Adding a new class
of detectable fault means adding an extractor or a probe, never touching the
engine.

**Why.** This is the difference between a product that grows and a pile of
special cases. It is also what makes the eval corpus meaningful — new fault
classes are added as data, not code.

**Trade-off.** Requires a disciplined subject-URI scheme (§2.3). Sloppiness there
breaks everything downstream, so subject construction is centralised in
`shared/culprit_model/` and covered by its own tests.

### D8 — The narrator is the only LLM, and it may not decide facts

**Chosen.** The existing invariant is strengthened and kept structurally
enforced. Extraction, comparison, probing, isolation and verification contain no
LLM call. The narrator renders an already-settled fault tree into prose and may
also rank hypotheses *within an already-computed set*. It may never create a
fact, a divergence, a reading, or a verdict.

**Enforcement.** The `lint-imports` contract is extended so `culprit_model`,
`probes`, `isolate` and `verify` may not import `rag`. The MCP server's existing
AST test — which proves the module never imports an LLM chat client — is
generalised into a reusable check applied to every deterministic package.

**Why.** This is the product's strongest defensible property. The vision states
it as a goal; it must be a build failure, not a goal.

**The test that keeps it honest:** `culprit check` and `culprit diagnose` must
produce complete, correct output with `LLM_PROVIDER=none`. That is a CI job, not
an aspiration.

**Amended 2026-11-03 — the network boundary is per package, and it is an
allowlist.** Phase 31 replaced the binary-wide ban on linking `net/http`,
because probes must make HTTP requests under `net.http.outbound` (§2.7).
Ratified: the binary may speak HTTP; the packages that compute findings may
not. But the test as built, `TestOnlyTheProbePackageMayLinkAnHTTPClient`, lists
six packages that must not link `net`, `net/http` or `crypto/tls` — so
`internal/capability`, `internal/render` and every package created later are
unchecked by default, and Phase 32's `internal/isolate` would be one of them.
That is a check that looks like a gate and isn't (standing invariant 9).
**The rule of record:** only `internal/probe` may link `net/http`; only
`internal/probe` and `internal/capture` may link `net` or `crypto/tls`; every
other package under `cli/internal/` may link none of them, enumerated with
`go list ./internal/...` so that a new package is covered the day it exists.
Fixed in Phase 31.1.

**Amended 2026-11-05 — there is no `LLM_PROVIDER=none` job today.** Phase 32
part 2 removed the narrative job and every LLM client, so nothing reads the
variable and a job that sets it would test nothing. What holds D8 now is
structural: no deterministic package can import an LLM client
(`check_no_llm_imports`, the `lint-imports` contracts). The job returns with
the narrator in Phase 35, where it means something again: every command
complete, only the prose absent.

---

## §2. The core model

This section is the shared vocabulary for every phase. Another agent executing
this plan should treat these definitions as binding.

### §2.1 Planes

`INTENT` · `CONFIGURED` · `OBSERVED`, as defined in §0.2. Baseline statistics are
derived from `OBSERVED` and are never a plane.

### §2.2 Fact

The atomic unit. Every extractor, every environment capture and every probe
emits Facts.

```
Fact
  plane          INTENT | CONFIGURED | OBSERVED
  subject        str    -- a subject URI, §2.3
  predicate      str    -- e.g. "exists", "request_schema", "audience", "nullable"
  value          json   -- canonicalised for comparison
  environment    str?   -- null for INTENT; required for CONFIGURED/OBSERVED
  provenance     Provenance
  captured_at    timestamptz
  capture_id     uuid   -- groups facts from one extraction run

Provenance
  source_kind    spec | introspection | static | test | assertion | observation
  extractor      str    -- "culprit-extract-python@0.3.1"
  artefact       str?   -- "openapi.json", "api/app/main.py"
  locator        str?   -- "L142", "$.paths./orders.post"
  confidence_rank int   -- §2.4
```

**Config values.** (Decided 2026-09-09; corrected 2026-09-09 after the Phase 26.1
audit showed the first version of this paragraph overclaimed.) A `CONFIGURED`
fact about a config key carries `value_shape` — type, length class, format class
— and **`value` is NULL by default**. `configured_facts` carries `grant_ref` and
a CHECK constraint `value IS NULL OR grant_ref IS NOT NULL`, so a literal value
can exist only in a row naming the explicit per-key grant that permitted it.

**What that constraint does and does not buy.** It protects `value` — the column
extractors are told not to use. It does *not* protect `value_shape`, which is
free-form JSONB and would accept
`{"type":"url","sample":"postgresql://u:hunter2@db/orders"}` with no grant at
all. Worse, `culprit_model.Fact` carries neither field, so **Postgres is
currently the only enforcement point**, and a capture bundle serialised to JSON
without ever being inserted — precisely the artefact §5 promises is safe to
attach to a bug report — is unprotected.

**`ValueShape` carries `scheme`, as a closed enum.** (Resolves Q7, 2026-09-09.)
Diagnosis genuinely needs it: "the application declares a `postgresql` URL and
the environment holds a `mysql` one" is a real fault class that is undetectable
without it. But it is an enum of known schemes — `postgresql`, `mysql`, `https`,
`redis`, `amqp`, … with `other` as the fallback — never a free string. A closed
enum cannot carry a secret; a free string always can. Same reasoning applies to
every field added to `ValueShape` from here: if it cannot be expressed as a
closed set or a bounded numeric class, it does not belong in the type.

The real fix is a **closed `ValueShape` type in `culprit_model`** that
structurally cannot hold a literal: a fixed set of fields (`type`,
`length_class`, `format`, `present`) with constrained values, not an open
mapping. Then serialisation is safe by construction, the database CHECK becomes
defence in depth rather than the only line, and `value_shape` as a column can be
narrow rather than free JSONB. **This lands in Phase 28**, where Facts are first
constructed and serialised for real. Until it does, the guarantee is partial and
`docs/LIMITS.md` says so.

### §2.3 Subject URIs

A stable, canonical identifier for the thing being asserted about. Comparison
only works if two sources describing the same thing produce the same subject, so
construction is centralised in `shared/culprit_model/subjects.py` (Python) and
`cli/internal/model/subjects.go` (Go), with a shared conformance test fixture.

```
component:orders-svc
connection:orders-svc->payments-svc
http:orders-svc/POST /api/v1/orders
http:orders-svc/POST /api/v1/orders#request.body
config:orders-svc/DATABASE_URL
schema:orders-db/public.orders
schema:orders-db/public.orders.total_cents
dep:orders-svc/stripe
image:orders-svc
auth:orders-svc->payments-svc/audience
```

Path templating is normalised (`/orders/{id}` and `/orders/:id` canonicalise
identically). This normalisation is the single highest-risk piece of code in the
extraction layer and gets exhaustive table-driven tests.

### §2.4 Intent confidence ranks

| Rank | Source | Example |
|---|---|---|
| 100 | Explicit developer assertion | `culprit.yaml` invariant |
| 90 | Runtime introspection of the app | `app.openapi()` |
| 80 | Committed machine-readable spec | `openapi.json`, migration file |
| 60 | Static extraction from framework code | route decorator |
| 50 | Static extraction from tests | `assert resp.status_code == 200` |
| 40 | Static extraction from client call sites | `fetch("/api/v2/users")` |
| 20 | Inference from observed traffic | a path seen in traces |

Rank orders reports and picks comparison defaults. **Rank never silently
discards a source.** Two INTENT facts with the same subject+predicate and
different values emit an `intent_conflict` divergence (§0.3).

### §2.5 Divergence

```
Divergence
  id
  kind           intent_conflict | intent_vs_configured | intent_vs_observed
                 | configured_vs_observed | env_vs_env | baseline_deviation
  subject        str
  predicate      str
  left           Fact
  right          Fact
  severity       breaks_request_path | degrades | cosmetic | unknown
  first_seen_at  timestamptz
  status         open | acknowledged | resolved | suppressed
```

`severity` is computed deterministically from the system model — a divergence on
a subject that lies on a known request path is `breaks_request_path`; one on an
unreferenced config key is `cosmetic`. It is never an LLM judgement.

### §2.6 Probe and Reading

```
ProbeManifest
  id             str    -- "probe.http.route_conformance"
  version        int
  effect         inspect | observe | interrogate | mutate
  capabilities   [str]  -- §2.7
  inputs         json-schema
  timeout_ms     int
  expected_from  INTENT | CONFIGURED | none
  produces       [subject_template, predicate]
  discriminates  [hypothesis_id]   -- what a result rules out
  cost           cheap | metered | intrusive

Reading
  probe_id, probe_version
  target          subject URI
  environment     str
  verdict         pass | fail | inconclusive | refused
  measured        json
  expected        json?
  expected_source Provenance?
  evidence        [{kind, value, redacted: bool}]
  reason          str?   -- required when inconclusive or refused
  taken_at        timestamptz
  expires_at      timestamptz
  agent_id        str
  grants_used     [str]
```

Four verdicts, not two. **`inconclusive`** means the probe ran and could not
establish the answer. **`refused`** means the agent lacked the capability. Both
are honest outputs and both appear in reports — "I could not check X because you
have not granted Y" is a feature, not an error.

`effect: mutate` fails manifest validation. No exceptions in this plan.

### §2.7 Capability grants

Coarse, named, human-legible. Granted per environment, per agent, in config the
user writes and reviews.

```
model.read              repo.read
config.read.names       -- names and shapes only, never values
config.read.values      -- opt-in, per-key allowlist
db.metadata.read        -- schema, constraints, migration version, NOT rows
db.rows.read            -- opt-in, per-table allowlist, redacted by default
net.dns.resolve         net.tcp.connect         net.tls.inspect
net.http.outbound
telemetry.logs.read     telemetry.metrics.read  telemetry.traces.read
deploy.metadata.read
process.exec.allowlist  -- named commands only
```

**No `*.write` capability exists.** Adding one is a design decision requiring its
own plan document, not a phase in this one.

### §2.8 Investigation

Replaces `incident_candidates` as the central object. An incident is something
that happened to you; an investigation is something you are doing.

```
Investigation
  id, opened_at, closed_at, environment
  symptom          {kind, subject, description, source}
  hypotheses       [Hypothesis]
  readings         [Reading]
  fault_tree       [FaultEdge]
  diagnosis        {root_subject, statement, confidence_rubric, remediation}
  verification     Verification?

FaultEdge
  from_subject, to_subject
  relation         symptom_of | propagates_to | caused_by
  established_by   [reading_id]     -- never empty
```

Every fault edge cites the readings that established it. An edge with no readings
cannot be created — that is the structural guarantee against narrative
masquerading as diagnosis.

**Amended 2026-11-04 — what establishes a symptom.** A write cannot be replayed
read-only, so the walk often cannot observe the symptom itself. A `symptom_of`
edge cites the readings that tie the symptom to its cause, which is what that
edge asserts. The symptom's *occurrence* is attested separately: by a reading,
when the walk reproduced it read-only, or otherwise by the report it came from
— and the investigation says which. A symptom that was only reported is never
presented as reproduced.

### §2.9 Confidence rubric — not a percentage

Replaces the LLM's `High|Medium|Low` string. Four independent booleans, reported
as a set, never collapsed into a number the model invents:

- **`reproduced`** — the failing probe failed again on a second run.
- **`discriminated`** — at least one reading ruled out a competing hypothesis,
  not merely supported this one.
- **`counterfactual`** — the same probe passes in a reference environment, or
  passed before a known change.
- **`verified`** — after a change, the failing probe now passes *and* every
  previously-passing probe in the set still passes.

"Reproduced, discriminated, not yet verified" is more actionable to a working
engineer than "94%", and unlike "94%" it is checkable.

---

## §3. The phases

Ten phases. Each leaves `main` runnable, deployable and coherent. Value lands
early: **Phase 29 is a shippable product on its own**, requiring no runtime
access, no telemetry and no account.

Standing invariants that hold in every phase below, carried forward from the
prior plans and extended:

1. Anomaly detection statistical, comparison deterministic, LLM only for
   narration — now CI-enforced across every deterministic package (D8).
2. `worker/app/db.py` and `api/app/db/models.py` must not drift —
   `scripts/check_schema_drift.py` remains a CI gate.
3. Least privilege per job. A new job, a new trust domain or a new write
   surface gets a new role, and a role's write grants are never widened. A read
   grant may be added to an existing role only for a table its *same* job needs
   beside one it already reads, with the justification written in the migration
   and the downgrade revoking it. (Clarified 2026-11-03, accepting Phase 31's
   `anomaly-detector` SELECT on `connections`.)
4. Migrations are historical snapshots and do not import mutable app code.
5. Secrets never enter CI.
6. Every new deterministic package is added to the `lint-imports` contract in the
   same commit that creates it.
7. Every phase adds its own limits to `docs/LIMITS.md` in the same commit.
8. **Every migration is round-trip tested against a real database in CI** —
   `upgrade head → downgrade base → upgrade head`. Added 2026-09-09 after Phase
   26.1 shipped a downgrade that rewrote SQL `NULL` to `'null'::jsonb`, so
   re-upgrading failed on its own new constraint.
   `scripts/check_migration_symmetry.py` passed that migration both before and
   after the fix and always will: it is a structural AST check and cannot see a
   data-dependent defect. A structural check that cannot fail on a real class of
   bug is not a gate for that class, and pretending otherwise is the exact error
   this product exists to stop.
9. **Every check declares its scanned roots, and a test asserts those roots cover
   the repository.** Added 2026-09-09. Two separate blind spots surfaced in two
   consecutive phases: `just lint` never covered `scripts/`, and the
   subject-construction lint never covered `api/tests/`. Both times a real
   violation sat unseen inside a green gate. The coverage of a check is itself a
   thing that has to be checked.
10. **A new gate is not accepted until a deliberate mutation has made it fail.**
    Added 2026-09-09. Phase 27 mutation-tested the new round-trip gate by
    removing `ON CONFLICT DO NOTHING` from a downgrade, expecting red — and it
    stayed green. The gate was fine; the *comment explaining why it worked* was
    wrong (the `GROUP BY` collapses the duplicates, not the `ON CONFLICT`).
    Removing the `GROUP BY` does fail it. A passing check is not evidence until
    you have shown the thing it is supposed to catch actually turns it red, and
    the mutation must target the mechanism you believe is load-bearing — that is
    how a wrong belief about your own gate gets caught. This is the same claim as
    §2.6's rule that a probe which cannot return `inconclusive` is a probe that
    guesses.
11. **Error text is output, and carries the same redaction obligations as a
    fact.** Added 2026-09-09. Phase 28's audits found four paths by which a
    credential escaped through an error: a non-canonical subject slipping past
    both the model's and the database's config-value checks; a CHECK violation
    surfacing as a 500 with Postgres's failing row in the log; the fix for that
    quoting the offending subject, and a subject is a fine place to hide a DSN;
    and `str(ValidationError)` rendering its input, which an extractor turns into
    a skip reason that travels inside the capture bundle — the artefact whose
    safety is the whole claim. **Three of those four were introduced by the fix
    for the previous one.** That is the real finding: redaction bolted on per
    call site will always have one more call site. It belongs at a single choke
    point — one serialiser that structurally cannot render a secret, applied to
    every outbound string, with error messages, skip reasons, probe
    `inconclusive`/`refused` reasons and log lines all inside its scope.
12. **Gates run on the merge result and in CI, not on the branch and not only
    locally.** Added 2026-09-10 after Phase 29's gates were green locally and CI
    failed on merge. Two distinct gaps, both instances of invariant 9 applied to
    the gate set itself rather than to lint roots:
    - **The tree that was tested is not the tree that gets merged.** Every phase
      branch is cut from a `main` that then moves underneath it. Local gates ran
      on the branch; the merge result was never run at all. Before reporting a
      phase complete, merge `origin/main` into the branch and re-run everything.
    - **CI is a superset of the local gates and a different environment.** It
      builds five images, Trivy-scans them, cross-compiles Go, generates frontend
      types from a live OpenAPI dump, and does it on Linux from a clean checkout
      — against a repository with no `.gitattributes` and unset `core.autocrlf`,
      where a file can pass on Windows and fail on Linux. `/verify` cannot see
      any of that, so a phase is not verified until CI is green on the merge
      result.

---

### Phase 26 — Truth repair and the three-plane schema

**1. Objective.** Remove every known-false claim from the repository, and land
the `Fact`/plane schema alongside the existing tables without changing any
current behaviour.

**2. Why this phase exists.** The reconnaissance found a security bug, three
fail-open defaults, a broken bootstrap path and a status file four phases stale.
Building on that is building on sand, and the repair is a few days. Landing the
new schema in the same phase means Phase 27 starts against a real foundation.

**3. Architectural changes.** None to runtime topology. Introduces the
`shared/culprit_model/` package as the home for planes, facts, subject URIs and
canonicalisation — imported by both `api/` and `worker/` as a path dependency,
exactly as `culprit_shared` already is.

**4. Components to create.**
- `shared/culprit_model/{__init__,planes,facts,subjects,canonical}.py`
- Migration: `intent_facts`, `configured_facts`, `readings` (hypertable),
  `divergences`, `captures`.
- `scripts/check_no_llm_imports.py` — generalises the MCP server's AST test into
  a reusable check over a configured package list.

**5. Existing components to modify.**
- `api/app/ingest_gateway/auth.py` — `authenticate()` must call `_reload_if_due()`
  on the hit path too, bounded by the existing 10s interval. Revoking a key must
  actually revoke it.
- `api/app/{auth,registry,postmortems,incidents}/config.py` — remove hardcoded
  dev-password fallbacks; fail loudly on unset `*_DATABASE_URL`, matching the
  migrations' existing `_require_env` behaviour.
- `scripts/bootstrap_env.py:237` — `IMAGE_REGISTRY` must be
  `ghcr.io/josh-heath123/culprit`.
- `worker/app/rag/job.py` — verify each cited `passage` is a real substring of
  the cited postmortem body; drop citations that are not, and record the drop.
- `api/.env.example` — add the four missing `*_DB_PASSWORD` entries.
- `CLAUDE.md` — bring the status section current through Phase 24 and point at
  this document.
- Migration adding HNSW indexes on `architecture_decisions.embedding` and
  `ai_change_records.embedding`.
- `worker/app/consumer.py` — quarantine unparseable stream entries to a
  `dead_letter` stream and ack them, instead of wedging the drain forever.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** `culprit_model.subjects.build(kind, **parts) -> str`
is the only sanctioned way to construct a subject URI. Direct string formatting
of subjects anywhere else is a lint failure from this phase forward.

**8. Data models.** As §2.2 and §2.5. `readings` is a Timescale hypertable with
1-day chunks, compression at 7 days, retention at 90 days (longer than
`raw_events` — readings are evidence, not telemetry).

**9. APIs.** None added.

**10. Configuration.** No new required variables. `.env.example` files corrected.

**11. Dependencies.** No new runtime dependencies.

**12. Security.** This phase *is* the security phase: the key-revocation fix and
the fail-open credential fix are the two findings that matter. Add a regression
test that revokes a key and asserts the next request with it fails, with no
intervening unknown-key request.

**13. Testing.** Regression test per bug fixed. Table-driven tests for subject
canonicalisation covering path templating across FastAPI, Flask, Express and
Django conventions. `check_no_llm_imports.py` runs in CI over
`shared/culprit_model`.

**14. Acceptance criteria.**
- A revoked ingest key stops authenticating within `_MIN_RELOAD_INTERVAL_S`
  (10s), on the first request after that interval elapses, with no intervening
  unknown-key request required. (Reworded 2026-09-09: the original wording,
  "rejected on the very next request", was untrue given the in-memory key
  cache, and making it literally true would mean a database round trip on the
  ingest hot path. The defect being fixed is that revocation previously took
  effect only by accident, when an unrelated unknown key forced a reload.)
- Every service refuses to start with an unset `*_DATABASE_URL`.
- `just quickstart` still produces an incident end to end.
- `alembic upgrade head` succeeds from an empty database using only
  `.env.example` as a guide.
- `CLAUDE.md` describes the repository as it actually is.

**15. Definition of done.** All of the above, merged to `main`, deployed, and
`docs/LIMITS.md` updated with the Phase 23 linking heuristic that was never
documented.

**16. Connects to next phase.** Phase 27 builds the system model on top of
`culprit_model` and needs subject URIs to already exist and be trustworthy.

**17. Do NOT implement yet.** No extractors. No probes. No CLI. Do not start
populating the new tables — they are created empty and stay empty this phase.

---

### Phase 27 — The system model (the circuit)

**1. Objective.** Replace the flat service registry with a typed, directed model
of components, connections and contracts, migrating existing data without
breaking the running deployment.

**2. Why this phase exists.** The vision's central abstraction is that a
component can be healthy while a *connection* is broken. The current schema
cannot express that: `service_dependencies` is an untyped pair of service ids
with no contract attached. Everything downstream — probes, isolation, divergence
severity — needs this first.

**3. Architectural changes.** `services`/`service_dependencies` become
`components`/`connections`. `observed_service_edges` becomes an *evidence source*
for proposed connections rather than a parallel table. Connections gain a
`contract_ref` pointing at intent facts.

**4. Components to create.**
- A CI job running the migration round trip of standing invariant 8 against a
  real TimescaleDB container, plus `scripts/check_scan_coverage.py` for
  invariant 9. Both are small, both close a gap found in Phase 26.1, and both
  belong here rather than in a later phase because every phase after this one
  ships migrations.
- Migration creating `components`, `connections`, `contracts`, with a data
  migration from the existing tables.
- `api/app/model/` — router, service, schemas for reading and editing the model.
- `shared/culprit_model/graph.py` — in-memory directed graph, request-path
  derivation, reachability. Pure, no I/O, mirroring the `scorer.py`/`state.py`
  split already established.
- `culprit.yaml` schema + loader — the declarative, committed description of a
  system, so the model is reproducible from a repo rather than clicked into a UI.

**5. Existing components to modify.**
- `api/app/registry/` — rewritten against the new tables, keeping its existing
  HTTP surface working (the frontend depends on it).
- `api/scripts/apply_services.py` → `apply_model.py`, reading `culprit.yaml`.
- `worker/app/correlation/job.py` — reads adjacency from `connections`.
- `frontend/src/routes/SettingsServices.tsx` — component/connection editing,
  connection types visible.

**6. Existing components to remove.** `shared/culprit_shared/services.py`'s
`SERVICE_ADJACENCY` demo fixture, once `demo-services/` reads `culprit.yaml`.

**7. Interfaces/contracts.**

```
Component
  id, name, kind          -- service | frontend | database | queue | external_api
                          -- | job | cache | object_store
  environment_scope       -- which environments this exists in
  labels                  json

Connection
  id, from_component, to_component
  kind                    -- http | grpc | sql | message | cache | dns | auth
  contract_id             -- nullable until Phase 28 populates it
  declared_by             -- culprit_yaml | inferred | accepted_suggestion
  criticality             -- on_request_path | background | unknown

Contract
  id, kind, subject_prefix
  facts                   -- reference to intent facts describing the interface
```

**8. Data models.** As above. `connections` keeps the composite unique
`(from_component, to_component, kind)` — two components may legitimately be
connected in more than one way.

**9. APIs.** `GET/POST/PATCH/DELETE /model/components`,
`/model/connections`, `GET /model/graph`, `POST /model/apply` (from
`culprit.yaml`). Existing `/services*` routes retained as thin aliases for one
release, then removed in Phase 30.

**10. Configuration.** `culprit.yaml` at repo root becomes the canonical model
source. Committed to the user's repo, reviewed like code.

**11. Dependencies.** None. (Corrected 2026-09-09: the original text said `networkx` is retained for directed traversal. That was wrong — `networkx` is a `worker/` dependency, while `graph.py` lives in `shared/`, which `api/` also installs. Using it there would have *added* a dependency to `api`, which is what field 11 was promising not to do. Plain BFS is correct here: the model is hundreds of nodes, not millions.)

**12. Security.** Model editing stays behind `require_admin`. `culprit.yaml`
contains no secrets by construction — it names config keys, never values, and
the loader rejects any value that looks like a credential.

**13. Testing.** Data-migration test from a populated Phase-26 database. Graph
tests for request-path derivation on a branching topology. A `culprit.yaml`
fixture describing a system Culprit did not author.

**14. Acceptance criteria.**
- An existing deployment upgrades with no service/dependency data loss.
- `culprit.yaml` round-trips **semantically**: apply then export produces a
  document semantically equal to the input, and export→apply→export is
  byte-identical from the second export onward (a fixed point). (Reworded
  2026-09-09. The original — "diff is empty" — is not satisfiable and was never
  the property that mattered: YAML comments do not exist in the document model,
  and whether `kind: http` was written or defaulted is not stored. Byte equality
  from the *first* export would test comment preservation, which is a convenience
  for humans editing the file, not a correctness property of the model. Semantic
  equality plus a fixed point tests exactly what the criterion is for — that
  `culprit.yaml` is a faithful, reproducible source of truth. The normalisation
  applied must be documented in `docs/LIMITS.md`, distinguishing what is
  unavoidable from what is a design choice.)
- `--export` does not silently destroy a hand-maintained file. Comments and
  formatting are lost by export, which is acceptable only if the user is told:
  either refuse to overwrite an existing file without `--force`, or warn.
- The dashboard renders components and typed connections.
- Given a symptom component, the model returns the ordered set of upstream
  connections on its request path.

**15. Definition of done.** Above, plus `demo-services/` described entirely by a
committed `culprit.yaml`.

**16. Connects to next phase.** Extractors in Phase 28 attach contracts to the
connections created here.

**17. Do NOT implement yet.** No contract *content* — connections may carry a
null `contract_id` this phase. No probes. No UI for fault trees.

---

### Phase 28 — The CLI, the extractor protocol, and intent extraction

**1. Objective.** Ship the `culprit` binary and the extractor plugin protocol,
and make `culprit intent` produce a complete `INTENT` fact set for a real
project.

**2. Why this phase exists.** Everything the product claims rests on knowing what
the system is *supposed* to do. This is the phase that makes the `INTENT` plane
real, and it is where the polyglot risk lives, so it is isolated rather than
bundled with comparison logic.

**3. Architectural changes.** Introduces Go into the repository (D2) and the
subprocess extractor contract (D3). The CLI works fully offline against a repo,
with no control plane and no account.

**4. Components to create.**
- `cli/` — Go module. `cmd/culprit/`, `internal/model/` (subject construction
  mirroring the Python), `internal/extract/` (orchestration + built-in artefact
  readers), `internal/render/`.
- **`ValueShape` in `shared/culprit_model/`** — a closed type with a fixed field
  set and constrained values, mirrored in `cli/internal/model/`. Constructing a
  `Fact` about a config key takes a `ValueShape`, never a free mapping, so a
  literal cannot be carried even in a bundle that never reaches Postgres. This
  is the Phase 26.1 remediation described in §2.2; `configured_facts.value_shape`
  narrows from free JSONB to match, in the same migration.
- `extractors/python/` — `culprit-extract-python`, published to PyPI, installed
  as a dev-dependency in the target project.
- `extractors/node/` — `culprit-extract-node`, published to npm.
- `docs/EXTRACTOR_PROTOCOL.md` — the versioned contract, so third parties can
  write extractors for Go, Ruby, Java without touching this repo.

**5. Existing components to modify.** `justfile` gains Go build targets. CI gains
a Go lint/test/build matrix entry and cross-compilation for linux/darwin,
amd64/arm64.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.**

```
# extractor request (stdin)
{ "protocol": 1, "root": "/abs/path", "want": ["http_routes","db_schema",
  "config_keys","client_calls","test_assertions"], "environment": null }

# extractor response (stdout, one JSON object)
{ "protocol": 1, "extractor": "culprit-extract-python@0.3.1",
  "facts": [ Fact, ... ],
  "skipped": [ {"want":"client_calls","reason":"no supported framework found"} ] }
```

Non-zero exit or malformed output degrades to `skipped` with a reason; it never
fails the run. An extractor that cannot answer says so — the same honesty rule as
probe `inconclusive`.

**8. Data models.** `Fact` as §2.2, written to `intent_facts` when a control
plane is configured; emitted as JSON to stdout when not.

**9. APIs.** `POST /facts/captures` on the control plane, accepting a capture
bundle. Authenticated with a project token, not a user JWT.

**10. Configuration.** `culprit.yaml` gains an `extract:` section naming
extractor commands and per-component source roots. No control-plane URL required
for local use.

**11. Dependencies.** Go: stdlib plus `go-tree-sitter` and cobra. Python
extractor: stdlib plus optional framework imports guarded by try/except. Node
extractor: tree-sitter only.

**12. Security.** Extractors execute user-project code by importing the
application — the same trust level as running the project's own tests, and it
must be documented as such in `docs/EXTRACTOR_PROTOCOL.md`. The CLI never
transmits config *values*, only key names and shapes; there is a redaction test
asserting no captured fact ever contains a string matching common secret
patterns.

**13. Testing.** A fixture corpus of at least four real projects — and **at least
two the author did not write**, in stacks the author does not control. This is a
hard requirement, not a nice-to-have: it is the only defence against building an
extractor that only works on FastAPI because `demo-services/` is FastAPI. Golden
files per fixture.

**14. Acceptance criteria.**
- `culprit intent` on a Python+React repository emits facts for server routes,
  client call sites, DB schema, migration head, config keys and dependency
  versions.
- Running it twice on an unchanged tree is **reproducible**: byte-identical with
  `SOURCE_DATE_EPOCH` pinned, and identical except for `captured_at` without it.
  (Reworded 2026-09-09. The original said "byte-identical" full stop, which is
  unsatisfiable while a fact carries a capture timestamp. Pinning the clock is
  the standard way to assert reproducibility — it is how reproducible builds are
  tested everywhere else — so this is a literal satisfaction of the property the
  criterion is for, once the criterion says what it means.)
- A `Fact` about a config key **cannot be constructed carrying a literal value**
  — not through the API, not by serialising a bundle that never touches the
  database. Proved by attempting it in a test, not by inspection.
- With no extractor installed, it still emits artefact-derived facts and reports
  precisely what it skipped and why.
- One static binary, no runtime installed, `curl | sh` documented.

**15. Definition of done.** Above, plus binaries built and installable from a
local checkout, and both extractor packages installable from a local path.

**Publication moved to Phase 29** (2026-09-09). Tagging `v0.1.0` and claiming the
names on PyPI and npm before Phase 29 makes the tool useful to anyone would burn
good package names on something nobody can yet get value from, and a published
`v0.1.0` invites installs against a CLI whose only verb prints an inventory. The
eval corpus installs the extractors from a local path, so nothing in this phase
needs a registry. Publication becomes real when Phase 29's criterion — a
confirmed finding in a project we neither wrote nor control — is met.

**16. Connects to next phase.** Phase 29 compares these facts. Nothing is
compared yet.

**17. Do NOT implement yet.** No comparison, no divergences, no network access of
any kind, no environment capture, no probes. `culprit intent` prints an inventory
and stops.

---

### Phase 29 — The divergence engine — *first shippable product*

**1. Objective.** `culprit check` finds real faults in a real repository, in CI,
with no runtime access, no telemetry, no baseline and no account.

**2. Why this phase exists.** This is the wedge. It is useful sixty seconds after
install, which is precisely what the current product is not — today Culprit needs
30 observations per metric and a written postmortem corpus before it says
anything useful. It also proves the whole thesis on the cheapest possible
substrate.

**3. Architectural changes.** The generic comparator (D7). Domain knowledge stays
in extractors.

**4. Components to create.**
- `cli/internal/diverge/` — the comparator. Groups facts by
  `(subject, predicate)`, canonicalises values, emits `Divergence`.
- `cli/internal/severity/` — deterministic severity from the model graph.
- `cli/internal/report/` — human, JSON, SARIF and JUnit output. SARIF matters:
  it makes findings appear natively in GitHub PR annotations, which is most of
  the adoption story for a CI tool.
- `culprit.yaml` `invariants:` section — explicit developer assertions at rank 100.
- **Unverifiable surface report** (§0.1) — subjects with exactly one intent
  source and no test coverage. Ships as `culprit check --unverifiable`.

**5. Existing components to modify.** CI gains a self-check job: Culprit runs
`culprit check` against its own repository. Dogfooding is the cheapest continuous
eval available.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** Exit codes: `0` clean, `1` divergences at or above
the configured severity, `2` execution error. Configurable via
`--fail-on=breaks_request_path|degrades|any`.

**8. Data models.** `Divergence` as §2.5. Suppressions live in `culprit.yaml`
with a required `reason` field and an optional `expires` date — an un-expiring
suppression with no reason fails validation.

**9. APIs.** `POST /divergences/captures` for history. Local use needs no API.

**10. Configuration.** `culprit.yaml` gains `invariants:`, `suppress:`,
`severity_overrides:`.

**11. Dependencies.** None new.

**12. Security.** Reports must never leak config values. Same redaction test as
Phase 28, applied to rendered output including SARIF.

**13. Testing.** Every fault class gets a fixture in the corpus with an expected
divergence set — this is the beginning of the eval suite. False-positive rate is
tracked as an explicit metric per fixture and reported in CI; a fixture whose
false-positive count rises fails the build.

**14. Acceptance criteria.**
- Detects a frontend calling a route the backend does not expose.
- Detects an ORM model whose column is absent from the migration head.
- Detects a config key read in code and absent from `.env.example`.
- Detects `openapi.json` disagreeing with the live route table
  (`intent_conflict`).
- Runs in under 30 seconds on a 200k-line repository.
- Produces zero findings on a fixture known to be correct — **the single most
  important criterion in this phase.**

**15. Definition of done.** Above, plus `culprit check` running against Culprit's
own repo in CI, and a README that shows real output from a real project. Plus
**publication, moved here from Phase 28**: tag `v0.1.0`, publish the binaries,
and release both extractor packages to PyPI and npm. This is the first point at
which a stranger installing them gets something worth having.

**16. Connects to next phase.** Phase 30 adds the `CONFIGURED` plane, which
multiplies the fault classes this same comparator can find without changing it.

**17. Do NOT implement yet.** No environment access. No probes. No LLM anywhere
near this path — `culprit check` must never make a network call to a model
provider, and a test asserts it.

---

### Phase 30 — Environment capture and cross-environment diff

**1. Objective.** Capture the `CONFIGURED` plane from an environment and diff
environments against each other and against `INTENT`.

**2. Why this phase exists.** "Works locally, fails in production" is the
universal, unowned developer problem, and it is unreachable without this plane.

**3. Architectural changes.** The CLI gains its first read access to a running
environment, under the capability model (§2.7). Still no active probing.

**4. Components to create.**
- `cli/internal/capture/` — env var names and shapes (never values), live DDL via
  metadata queries, migration version, image digests, installed package versions,
  DNS resolvability, TLS certificate expiry, reachable ports.
- `cli/internal/capability/` — grant parsing, enforcement, and the `refused`
  verdict path.
- Adapters: Docker/Compose, Kubernetes, plain process, and a generic
  `exec`-allowlist adapter for anything else.
- `culprit env capture` / `culprit diff <a> <b>`.

**5. Existing components to modify.** `api/app/model/` stores captures.
`docker-compose.prod.yml` gains an optional agent service, off by default.

**6. Existing components to remove.** The `/services*` alias routes retained in
Phase 27.

**7. Interfaces/contracts.** A capture is a signed, timestamped bundle of
`CONFIGURED` facts plus the grant set that produced it, so a reader can tell what
was *not* looked at.

**8. Data models.** `configured_facts` + `captures` as created in Phase 26.

**9. APIs.** `POST /captures`, `GET /captures/{id}`, `GET /captures/diff?a=&b=`.

**10. Configuration.** `culprit.yaml` gains `environments:` with per-environment
adapter config and grants.

**11. Dependencies.** Go: `client-go` for Kubernetes, Docker SDK. Both optional
build tags so the binary stays small when unused.

**12. Security.** The most important phase for this. Config **values** are never
captured without `config.read.values` plus a per-key allowlist. Database access
is metadata-only under `db.metadata.read`. Every capture records which grants
were used and which facts were `refused`, so the output is auditable. A capture
bundle is safe to attach to a bug report by construction, and there is a test
asserting that.

**13. Testing.** Capture against a docker-compose fixture and a kind cluster.
Redaction tests. Grant-enforcement tests asserting `refused` rather than silent
omission.

**14. Acceptance criteria.**
- `culprit diff staging production` reports a missing env var required by an
  intent fact, ranked `breaks_request_path`.
- Detects live DDL behind the migration head.
- Detects an image digest mismatch.
- With only `config.read.names` granted, values never appear in output and the
  report says which checks were `refused`.

**15. Definition of done.** Above, plus `docs/PERMISSIONS.md` documenting every
grant in plain language, written for someone deciding what to give a tool access
to.

**16. Connects to next phase.** Phase 31 adds active interrogation on top of this
passive capture.

**17. Do NOT implement yet.** No requests into the system under test. No writes.
No agent daemon — capture is a one-shot CLI invocation this phase.

---

### Phase 31 — Probes

**1. Objective.** Make the probe a first-class, manifest-declared, capability-
gated abstraction, and ship the core catalogue.

**2. Why this phase exists.** Passive comparison cannot answer "can A actually
reach B from where A sits". This is the multimeter's defining property: an active
reading taken at a chosen point.

**3. Architectural changes.** Probes execute in the `culprit` binary. Manifests
are data, not code, so the catalogue is extensible without recompiling the engine.

**4. Components to create.**
- `cli/internal/probe/` — manifest loader, validator (rejects `effect: mutate`),
  runner with timeout and concurrency control, reading emitter.
- Core catalogue: `probe.net.dns_resolve`, `probe.net.tcp_connect`,
  `probe.net.tls_validity`, `probe.http.reachable`,
  `probe.http.route_conformance`, `probe.http.schema_conformance`,
  `probe.auth.token_shape` (claims, audience, issuer, expiry — never the token),
  `probe.auth.propagation`, `probe.db.connect`, `probe.db.schema_conformance`,
  `probe.config.present`, `probe.dep.version`, `probe.edge.impedance`.
- `probe.edge.impedance` re-sites the existing EWMA scorer (D5): latency and
  error rate attributed **per connection**, not per service.

**5. Existing components to modify.** `worker/app/anomaly/` — its job now writes
impedance readings keyed by connection subject. `scorer.py`, `state.py` and their
tests are unchanged.

**6. Existing components to remove.** None this phase.

**7. Interfaces/contracts.** `ProbeManifest` and `Reading` as §2.6. Third-party
probes are manifests plus an `exec` procedure under `process.exec.allowlist`.

**8. Data models.** `readings` hypertable, populated for the first time.

**9. APIs.** `POST /readings`, `GET /probes` (catalogue),
`POST /probes/{id}/run`.

**10. Configuration.** `culprit.yaml` gains `probes:` for enable/disable, timeout
overrides and per-environment applicability.

**11. Dependencies.** Go stdlib `net`, `crypto/tls`, `database/sql` with `pgx`.

**12. Security.** Every probe declares required capabilities; the runner refuses
to execute one whose capabilities are not granted, emitting `refused`. Auth
probes inspect token *structure* and never log token material — enforced by a
test that runs the auth probes against a fixture token and greps the full output
for it.

**13. Testing.** Each probe gets a fixture where it must return `pass`, one where
it must return `fail`, and one where it must return `inconclusive`. The
inconclusive case is mandatory — a probe that cannot admit uncertainty is a probe
that guesses.

**14. Acceptance criteria.**
- With the demo stack running, `culprit probe connection:order-service->inventory-service`
  returns readings for reachability, TLS, route conformance and impedance.
- *(Reworded 2026-11-03, refined 2026-11-04 — see the reviews below.)* With the
  `culprit` binary run inside container A, blocking the network path from A to B
  flips A's reachability probes for B — `probe.net.tcp_connect` and
  `probe.http.reachable`, the same path at two layers — to `fail`, while both
  components' own health probes, taken from the host, stay `pass`: the
  broken-relationship case, demonstrated.
- Every probe returns `inconclusive` with a reason rather than a guess when its
  preconditions are unmet.
- No probe in the catalogue declares `effect: mutate`; manifest validation
  rejects one that tries.

**15. Definition of done.** Above, plus `docs/PROBES.md` documenting each probe's
inputs, effect, capabilities, expected source and failure conditions.

**16. Connects to next phase.** Phase 32 chooses which probes to run and in what
order.

**17. Do NOT implement yet.** No automatic probe selection — this phase runs
probes a human or a script names. No fault trees. No synthetic transactions
against write endpoints, in this or any later phase of this plan.

**Architecture review, 2026-11-03.** Every item the Phase 31 run report left
open, decided:

- **Criterion 2** is reworded above. A probe sees the network from wherever the
  binary runs; that location is the vantage point, and the reading records it
  in `agent_id`. A probe run on the host cannot see a partition between two
  containers, so the criterion now says where the binary runs. How the path is
  blocked is the implementer's choice, provided neither container is stopped.
  Demonstrated in Phase 31.1.
- **The network boundary** moved from binary-wide to per package — ratified,
  and tightened into an allowlist (D8, amended).
- **`anomaly-detector` SELECT on `connections`** — accepted; standing
  invariant 3 clarified to say what it means.
- **Four endpoints share `CULPRIT_PROJECT_TOKEN`**, not three as the run report
  said: `POST /readings`, `/facts/captures`, `/divergences/captures` and
  `/model/captures`. Deferred to Phase 33 as an acceptance criterion. While one
  CI job holds the token for all four, splitting it buys nothing; it becomes a
  hole when a probe runner sits on a production host.
- **Field 13** — table-driven cases with a coverage gate meet "each probe gets a
  fixture". On-disk fixture directories were not meant.
- **Field 9** — `POST /probes/{id}/run` returns an honest 503 naming the local
  command until Phase 33's agent transport exists. Accepted.
- **Field 4** — the impedance attribution rule (a peer attribute; else exactly
  one declared inbound connection; else emit nothing) is the rule of record.
- **Q12** — capture's passive DNS/TCP/TLS checks and `probe.net.*` both exist,
  because a probe must be able to answer `inconclusive` and a capture records
  yes or no. Accepted, with the duplication cost stated in LIMITS.
- **`request.Expectation` is never populated, and the database, config and
  dependency probes have no data source in the CLI.** This is the important
  one. The comparison the planes exist for is not yet connected for probes, and
  Phase 32 selects probes by what they discriminate against an expectation.
  Phase 31.1 does it, before Phase 32.
- **The D2 revisit trigger** fired, and was replaced (D1 and D2, amended).

---

### Phase 31.1 — Close the probe loop

**1. Objective.** Make `culprit probe` compare a reading against what the
system declares, end to end; give the database, config and dependency probes a
data source; and demonstrate Phase 31's criteria against the running demo stack.

**2. Why this phase exists.** Phase 31 built the machinery honestly and left
its central comparison unconnected: `request.Expectation` is never populated,
so `expected_source` is always null and every manifest's `expected_from` is
inert. Five probes return `inconclusive` from the CLI because nothing
constructs their data source. A probe that cannot compare against intent is a
measurement with no reference, and Phase 32's isolation walk depends on exactly
that comparison.

**3. Architectural changes.** None to the model. `culprit probe` resolves
expectations from the same extraction `culprit check` already runs.

**4. Components to create.**
- Expectation resolution. For each probe request, take the INTENT facts that
  `culprit check`'s extraction produces for the same `culprit.yaml` — the same
  extractors, not a second extraction path — select those whose subject and
  predicate match the manifest's `produces`, and populate `request.Expectation`
  with the highest `confidence_rank` (§2.4). The reading's `expected_source` is
  that fact's provenance. Where two INTENT facts disagree, the probe still uses
  the highest-ranked one and the reading names the conflict: rank picks a
  default, it never discards (§0.3). Where a manifest says
  `expected_from: CONFIGURED`, the source is the Phase 30 capture of the named
  environment.
- Data sources for `probe.db.connect`, `probe.db.schema_conformance`,
  `probe.config.present` and `probe.dep.version`. The database client reuses
  what `internal/capture` already uses (pgx) rather than adding a second one;
  config and installed versions are read through the Phase 30 capture adapters.
  Each stays gated on the capabilities its manifest already declares.
- The network boundary test inverted to an allowlist (D8, amended).
- `.trivyignore` emptied of its five entries. They were accepted on
  2026-08-04 for the published Caddy image, which the frontend no longer uses,
  and the file says to delete them once every image has been scanned without
  them — `fail-fast: false` (2026-11-03) now scans every image in one run. The
  file applies to every image, and three of the five are Go standard-library
  advisories, so an entry written for Caddy can now hide a real finding in the
  `culprit` CLI image, which is a Go binary. If an image goes red without them,
  fix the image; never restore a line.

**5. Existing components to modify.** `cli/cmd/culprit/probe.go`,
`cli/internal/probe/`, `cli/cmd/culprit/check_test.go`, the demo stack's
compose file (the static binary mounted into the containers criterion 2
needs), `demo-services/culprit.yaml` (grants for the `local` environment),
`.claude/rules/database.md` (to standing invariant 3's clarified wording),
`.trivyignore`, `docs/PROBES.md`, and `docs/LIMITS.md`, whose "Six probes have no data source"
section lists five.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** `ProbeManifest` and `Reading` unchanged. If
populating expectations needs a change to either, stop and escalate (handoff
§6).

**8. Data models.** None. No migration.

**9. APIs.** None.

**10. Configuration.** Nothing new in the schema. The demo's `culprit.yaml`
grants what the newly wired probes need in `local`.

**11. Dependencies.** None new.

**12. Security.** A database probe reads metadata, never rows (§0.4). The DSN it
uses is a credential: it reaches the probe from the environment, by the name
`culprit.yaml` gives, and never appears in a reading, a reason, an error or a
log line. Redaction stays at `model.RedactReading`, the one choke point. A test
asserts that a fixture DSN's password is absent from the text and JSON output
of a *failing* database probe, because failure is where credentials escape
(standing invariant 11).

**13. Testing.** The existing pass, fail and inconclusive fixtures for every
newly wired probe, plus at least one run of each against the real demo stack,
reported. A test that `expected_source` is set whenever a matching INTENT fact
exists, and that the probe returns `inconclusive` with a reason when none does.
The allowlist mutation-tested by adding a package that links `net/http`: red,
with no edit to the test.

**14. Acceptance criteria.**
- Phase 31's criterion 1, against the running demo stack. A reading whose
  verdict is `inconclusive` counts only if its reason is true — for impedance,
  that the worker produces it.
- Phase 31's criterion 2, as reworded.
- With a route the demo both declares and serves,
  `probe.http.route_conformance` returns `pass` with `expected_source` naming
  the declaring artefact; with the declaration changed to disagree with what is
  served, it returns `fail`. INTENT against OBSERVED, end to end.
- `probe.db.schema_conformance` against the demo database returns `pass`, and
  returns `fail` naming the column after a column the code declares is dropped
  by hand. *(Refined 2026-11-04: the expectation comes from the highest-ranked
  source — ORM introspection at rank 90, not the migration chain at 80 (§2.4).)*
- No fixture credential appears in any reading, in text or in JSON.
- A new package under `cli/internal/` that links `net/http` turns the boundary
  test red with no edit to the test.
- `.trivyignore` holds no entries, and every image's scan is green in CI.

**15. Definition of done.** Above, plus `docs/PROBES.md` and `docs/LIMITS.md`
saying what is now wired, what still is not, and why. The run report replaces
the whole of the handoff's §5: earlier reports live in git history, and every
`/next` loads that file.

**16. Connects to next phase.** Phase 31.2 can show probes comparing against
intent; Phase 32 selects probes by what they discriminate.

**17. Do NOT implement yet.** No probe selection, no fault trees, no new probes,
no new capabilities, no agent transport, and no change to how impedance is
produced.


**Architecture review, 2026-11-04 — signed off.** Complete: merged via PR #20
(`4f69ab3`), CI green on the merge result (run 41789133416, every job, Trivy
blocking with `.trivyignore` empty), every criterion executed against the live
demo stack and executed again by `phase-auditor`. Checked on disk: the ignore
file holds no entries, and `TestTheNetworkBoundaryIsAnAllowlist` enumerates
`internal/...` rather than naming packages. Decisions on what the run report
left open:

- **Criterion 2** refined, above. Claude Code was right: a REJECT rule in A's
  namespace cuts both directions, and `tcp_connect` and `http.reachable` are
  one path at two layers, so "exactly one probe" could never be true.
- **Criterion 4** refined, above. It named the lower-ranked source.
- **Criteria 3 and 4 ran against Culprit's own api**, not the demo services,
  because the demo declares no `extract:`. Accepted: a real FastAPI service
  introspected at rank 90 is the stronger test.
- **Field 13 is partly met.** `probe.config.present` and `probe.dep.version`
  were never run against a live stack. Carried into Phase 31.2, which may not
  show either until it has run them.
- **Conflict evidence renders a fact's value verbatim** (`conflictEvidence` in
  `internal/probe/expect.go`). Unreachable for a secret today, because no probe
  measures against a CONFIGURED expectation, but it is redaction by call site
  again (standing invariant 11). **First item of Phase 32**, before any probe
  can measure against CONFIGURED.
- **The catalogue mirror's test checks three fields.** Phase 32 starts selecting
  probes by their manifests, so a hand-maintained mirror becomes a liability.
  **Second item of Phase 32:** the mirror is generated from the Go catalogue
  and compared whole, like the schema-drift check.
- **The partition used for criterion 2 is fault injection.** It may become part
  of Phase 32's fault library — test harness, demo stack, CI — because Phase
  32's field 13 requires network-partition faults. It never becomes a probe, a
  capability, or anything the `culprit` binary or an agent does: injecting a
  fault mutates the system, and §0.4 holds.
- **The local stack's `infra/.env.prod` predates Phase 28.** That is a task for
  the human, not a phase, and LIMITS now says why `just quickstart` cannot fix it.

---

### Phase 31.2 — Present what works

**1. Objective.** Make the repository explain itself to a first-time visitor —
a developer, an interviewer, a recruiter — using only what works today, and
remove anything in the interface that pretends otherwise.

**2. Why this phase exists.** `docs/PRODUCTISATION.md` (Malcolm, 2026-11-03)
asks for a product someone can open and understand at once, with nothing shown
that does not work. It is folded into this plan rather than run as one
overhaul, because the web UI today is the incident copilot that Phase 32
replaces: restyling it now would be done twice, and a demo of it would show the
half of Culprit being retired. What is finished and demonstrable now is the
CLI. This phase presents that, and makes the existing UI honest without
redesigning it. Phase 32.1 does the interface.

**3. Architectural changes.** None.

**4. Components to create.**
- `README.md`, rebuilt to `docs/PRODUCTISATION.md` §6's structure and centred
  on the CLI: the problem, who has it, and why it matters; `check`, `diff` and
  `probe` with real output; how it works — three planes, facts, divergences,
  probes, readings — with an architecture diagram and a data-flow diagram in
  Mermaid, which GitHub renders; the stack by role, listing only what is used;
  the architecture and the reasons behind it (D1–D8, in plain language);
  installation, configuration and one worked end-to-end example; testing — the
  `just` recipes and what each covers; project structure; future work as the
  remaining phases, stated as plans. The current README's strongest material —
  the real `check` output, the self-check story, "Not checked is not filler" —
  is kept, not rewritten for its own sake. The web UI is described as what it
  is and not showcased. No video link until a video exists.
- Terminal captures for the README, generated from real runs by a command
  committed in the repository, so anyone can regenerate them.

**5. Existing components to modify.** `README.md`; `docs/INSTALL.md` and any
setup document the README points to; frontend files only where the truth pass
(field 13) finds something broken.

**6. Existing components to remove.** Any UI element that does nothing, calls
an API that no longer exists (Phase 27 removed `/services`), or presents
hard-coded data as real — removed, where it cannot be fixed small.

**7. Interfaces/contracts.** None.

**8. Data models.** None.

**9. APIs.** None.

**10. Configuration.** None.

**11. Dependencies.** None new.

**12. Security.** Captures, examples and diagrams contain no real hostnames,
tokens, keys or DSNs — synthetic values only, as for extraction (D3).

**13. Testing.** The setup instructions are followed literally from a fresh
clone in a temporary directory, not the working tree, and every step that
needed something the README did not say is fixed in the README. The frontend
truth pass: every route, link, button and form exercised against a running
stack, with the browser console and network log read on each.

**14. Acceptance criteria.**
- Every command in the README's setup and usage sections was run from a fresh
  clone and produced what the README shows; the run report lists them.
- Every image in the README was produced from a real run by a committed command.
- The `phase-auditor`, given the README and the code but not this phase's
  transcript, finds no claim the code does not support.
- Every route loads, and every success path completes, with zero console
  errors and zero failed requests. On every error path a test provokes
  deliberately, the only console errors and failed requests are the provoked
  ones, and each is shown to the user as a message. A `204` is judged by the
  server's response, not by the browser's `ERR_ABORTED` report. No control
  does nothing. *(Refined 2026-11-04: as first worded this was untestable on
  error paths, where the browser logs every deliberate 4xx as an error.)*
- Both diagrams render on GitHub.
- `culprit.co.za` is linked only if the VM remediation is verified done; until
  then it is not linked at all.

**15. Definition of done.** Above, plus `docs/LIMITS.md` updated for anything
the truth pass removed or found.

**16. Connects to next phase.** Phase 32 builds the product's centre; Phase 32.1
designs around it and adds the screenshots and video this phase deliberately
leaves out.

**17. Do NOT implement yet.** No visual redesign, no design system, no new UI
features, no new dependencies, no demonstration video, and no publication —
`v0.1.0`, PyPI and npm still wait for a confirmed finding in a project neither
written nor controlled by us (§5).


**Carried in from Phase 31.1 (2026-11-04).**
- `probe.config.present` and `probe.dep.version` were never run against a live
  stack. Run each against the demo stack before the README shows it. If
  `dep.version` cannot reach a verdict there (the demo declares no `packages:`
  command), the README says so rather than showing it.
- The fresh-clone run (field 13) must not share the existing stack's volumes or
  ports — give it its own compose project name. Expect what 31.1 met on this
  machine: a stale `infra/.env.prod`, and port 80 already held by another
  server. What a new user would also hit goes into the README; what is
  particular to this machine goes into the run report.


**Architecture review, 2026-11-04 — before CI.** Decisions on what the run
report left open, and an independent re-check of criterion 3:

- **The justfile fix is ratified.** Field 5's list was incomplete: field 13
  required setup to work from a fresh clone, and the quickstart could not
  build there. One change: the recipe fetches `openapi-typescript` with
  `npx -y`, outside the frontend lockfile's integrity hashes — a supply-chain
  gap in a command every new user runs. It generates the types the way CI
  does, `npm ci && npm run generate-types` inside the container.
- **Criterion 4 is refined** (above).
- **The API lets an admin remove the last admin.** The dashboard's one-click
  route is closed and `just create-user <name> --role admin` recovers an
  install, so it is not urgent; but it is a server-side invariant and belongs
  on the server. **Third item of Phase 32.**
- **A failed narrative job stays `pending` for good.** Not fixed in the
  incident copilot, which Phase 32 demotes; LIMITS and the panel now say so.
  Phase 35's narrator must show a failure as a status (added there).
- **Criterion 3, re-checked by the architecture session**, because the
  `phase-auditor` pass came before the last fixes. Supported on inspection:
  thirteen roles; PostgreSQL 16; the extractors' stacks; both LLM providers;
  the sealed, optionally signed capture envelope; the one test that renders
  every report format and greps for a config value; the network allowlist;
  thirteen probes; the eval suites; the licence; the database-roles rules
  arguing their exceptions; the 484-facts story (Phase 29's run report). Not
  supported — fixed on this branch before merge:
  - "a three-component repository": the demo declares five components —
    three services and two databases — and its own header comment says two;
  - Trivy "unfixed ones are reported, not blocking": `ignore-unfixed: true`
    drops them from the report entirely;
  - "CI runs all of it": CI does not run `just self-check-coverage`;
  - the self-check's "9 gaps" and the coverage command's "368" are not
    evidenced in the run report — re-run both, and print what they print;
  - `docs/LIMITS.md` says SARIF annotations cannot appear on Culprit's pull
    requests because "this repository is private". It is public, so that
    reason no longer holds. Restoring the upload is Phase 32.1's.

---

### Phase 32 — Fault isolation and the Investigation

**1. Objective.** Given a symptom, walk the model, choose discriminating probes,
and produce a fault tree that separates symptom from propagation from root cause.

**2. Why this phase exists.** This is the product. Everything before it is
instrumentation; this is the thing a developer actually wants.

**Carried in from Phase 27.** Correlation currently ignores `connections.kind`,
so an `http` edge and a `cache` edge are treated as equally causal. Phase 27
recorded this rather than fixing it, correctly — its own first criterion was that
nothing is lost, and changing correlation behaviour there would have violated it.
The isolation walk designed here replaces that logic outright, so this is where
edge kind starts to matter: a typed edge is the whole point of the model.

**3. Architectural changes.** `Investigation` replaces `incident_candidates` as
the central object. The undirected correlation engine is deleted (D5).

**4. Components to create.**
- `cli/internal/isolate/` — hypothesis space construction from the model,
  probe selection by `discriminates`, bisection over the request path, fault-tree
  assembly, termination conditions.
- `api/app/investigations/` — router, service, schemas.
- `frontend/src/routes/Investigation.tsx` — fault tree with the boundary marked,
  every edge expandable to the readings that established it.
- `culprit diagnose "<symptom>"` — accepts a failing endpoint, a trace id, an
  error signature or a component name.

**5. Existing components to modify.**
- `worker/app/rag/` — demoted. The postmortem corpus becomes a *hypothesis
  prior* that reorders an already-computed hypothesis set. It may not add a
  hypothesis, and it may not produce a diagnosis. Enforced by the extended
  `lint-imports` contract (D8).
- `frontend/src/components/incident-detail/Evidence.tsx` — repointed at readings,
  which is what it should have been citing all along.

**6. Existing components to remove.**
- `worker/app/correlation/graph.py`, `worker/app/correlation/job.py` and
  `worker/tests/test_correlation_graph.py`. Reason: `nx.Graph` is undirected and
  the isolation walk requires direction, edge types and contracts. This is a
  structural mismatch, not a tuning problem.
- `incident_candidates` and `incident_anomalies` are retained read-only for one
  release with a data migration into `investigations`, then dropped in Phase 34.

**7. Interfaces/contracts.** `Investigation` and `FaultEdge` as §2.8. **A fault
edge cannot be created without at least one establishing reading** — enforced by
a `NOT NULL` constraint on a non-empty array and a database-level check.

**8. Data models.** `investigations`, `hypotheses`, `fault_edges`,
`investigation_readings`.

**9. APIs.** `POST /investigations`, `GET /investigations/{id}`,
`POST /investigations/{id}/probe`, `GET /investigations/{id}/tree`.

**10. Configuration.** `culprit.yaml` gains `isolation:` — max probes per
investigation, max wall-clock, per-environment probe budget.

**11. Dependencies.** None new.

**12. Security.** An investigation may only run probes whose capabilities are
granted in the target environment; the tree records which branches were
unexplored due to `refused` readings, so a partial diagnosis is visibly partial.

**13. Testing.** The fault library: every fault injectable in
`demo-services/shared/faults.py` gets an expected diagnosis — expected root
subject, expected fault-tree shape, expected confidence rubric. Extended beyond
latency/error-rate to include config faults, contract faults, auth-audience
faults and network-partition faults. **This is the regression suite for the
product's core claim and it is not optional.**

**14. Acceptance criteria.**
- Injecting an auth-audience mismatch between two demo services produces a
  complete investigation whose root is `auth:<caller>-><callee>/audience` —
  neither the caller component nor the symptom. *(Refined 2026-11-04.)*
- The fault tree distinguishes symptom, propagation and root, and every edge
  cites readings.
- Isolation is logarithmic, counted: with a fault at every position on a
  synthetic chain of 7 components and of 64, request probes stay at or under
  ⌈log₂ n⌉, and total probe executions on 64 stay at or under 12. *(Refined
  2026-11-04: at six hops the constants dominate, so it is asserted at 64 too.)*
- `LLM_PROVIDER=none` produces a complete, correct fault tree. Only the prose
  summary is absent.

**15. Definition of done.** Above, plus the fault library running in CI on every
push.

**16. Connects to next phase.** Phase 33 lets this run against production.

**17. Do NOT implement yet.** No remediation *application* — Culprit recommends,
it does not change the user's system. No verification loop yet. No production
agent.

**Added 2026-11-03.**
- **Where the walk runs.** In the binary, always (D1 and D2, amended). Until
  Phase 33, an investigation is opened by `culprit diagnose`, which runs the
  walk and uploads the result; the dashboard displays it. A dashboard control
  that *opens* an investigation needs a binary to hand the symptom to, and is
  not built before Phase 33. When it is, the control plane hands the symptom to
  an agent and stores the tree that comes back. Python never re-implements the
  walk.
- **`internal/isolate` does not import `internal/probe`.** It takes a probe
  runner through an interface that `cmd/culprit` supplies, so the isolation
  package links no network package and the D8 boundary holds with no exception.
- **Network-partition faults need a vantage point.** The fault library's
  partition cases (field 13) run with the binary inside the source container,
  as Phase 31.1 established. Where the walk cannot place a probe where it needs
  one, the tree records that branch as unexplored — the same treatment as
  `refused`.
- **Build the Investigation view functionally, on the existing component
  library.** The visual system arrives in Phase 32.1; do not design it twice.


**Carried in from Phase 31.1 (2026-11-04) — do these first.**
1. **Evidence never renders a CONFIGURED value.** Every place a reading's
   evidence or reason renders a fact's value goes through one function, and
   that function renders a CONFIGURED fact as its `ValueShape`, never its
   value. Test it with a granted config value: absent from text and JSON output,
   on pass and on fail.
2. **The probe catalogue mirror is generated.** `api/app/readings/catalogue.json`
   is produced from the Go catalogue by a command, and a drift check compares
   the whole document, not three fields. Mutation-tested (standing invariant 10).


**Added 2026-11-04 — third item: the last admin cannot be removed.**
`PATCH /users/{id}` and `DELETE /users/{id}` refuse, with a 409, to demote,
disable or delete the last active admin. The count and the change happen in
one transaction with the admin rows locked, so two admins demoting each other
at the same moment cannot both succeed. A test for each route and one for the
concurrent case. Found by Phase 31.2's truth pass.


**How Phase 32 is run — decided 2026-11-04.** Where this block and the fields
above differ, this block wins.

**Two parts, two `/next` runs, one architecture review between them.** This is
the largest phase in the plan, and its core claim — the walk finds the root,
not the symptom — should be proven before storage and screens are built
around it.

- **Part 1 — the walk, in the binary.** Carried-in items 1 and 2; the
  `Investigation`, `Hypothesis` and `FaultEdge` model in `culprit_model`, Go
  and Python, with a conformance fixture both read, written first as
  `Reading`'s was — a `FaultEdge` with no establishing reading cannot be
  constructed; `cli/internal/isolate/`; `culprit diagnose`; `isolation:` in
  `culprit.yaml`; the fault library and its CI job. Output is the
  investigation as text and JSON. Criteria: all four of field 14, and field
  15's fault library running in CI. No migration, no API, no frontend, no
  worker change.
- **Part 2 — the investigation in the control plane.** Field 8's tables, with
  field 7's rule enforced by the database; `POST /investigations` (ingesting
  what `culprit diagnose` wrote) and the reads; the Investigation view, built
  functionally; `Evidence.tsx` repointed at readings; the correlation engine
  removed with its data migration (field 6); the third carried-in item (the
  last admin); and README, quickstart and LIMITS brought back in line. After
  this part the quickstart's fault no longer produces an incident, so what the
  README shows must change with it — Phase 31.2's standard holds. Its criteria
  are written when part 1 is signed off.

**Decisions.**
- **`culprit diagnose` accepts a subject URI, a failing endpoint
  (`METHOD URL`) or a component name.** Not a trace id or an error signature:
  resolving either needs telemetry, which the binary cannot read — it has no
  client to the control plane before Phase 33's transport (D1 and D2,
  amended). They come back when the agent can read telemetry.
- **No postmortem prior in Phase 32.** Field 5 assumed the walk ran where the
  corpus lives. It runs in the binary, which never sees it. The walk is
  deterministic and chooses probes by `discriminates` alone. The incident
  narrative job goes with the correlation engine in part 2; the postmortem
  corpus and its editor stay. Ranking open hypotheses with the corpus belongs
  to the narrator, in Phase 35, under D8.
- **`POST /investigations/{id}/probe` is not built until Phase 33.** Running a
  probe from the control plane needs an agent, and an endpoint that can only
  answer 503 is not added a second time.
- **The binary does not upload.** `culprit diagnose --format json` writes the
  investigation; the quickstart and CI post it to `POST /investigations`,
  authenticated like the capture endpoints. The binary gains a client to the
  control plane only with Phase 33's transport — which is also when the
  project token is scoped down.
- **The confidence rubric (§2.9).** `reproduced`: the failing probe is run
  again and fails again. `discriminated`: at least one reading ruled out a
  competing hypothesis. `counterfactual`: the same probe passes in a
  reference environment named on the command line. `verified`: always false,
  with its reason, until Phase 34.
- **The fault library's faults are test harness.** The demo services gain what
  the criteria need — a config fault, a contract fault, an audience check
  between two services, and Phase 31.1's partition — in `demo-services/`,
  beside the existing fault injection. None of it is a probe, a capability, or
  anything the binary does.
- **The six-hop criterion runs against a synthetic model and a fake runner
  that counts executions**, not the demo stack, which has three services.


**Architecture review of part 1, 2026-11-04 — signed off.** Complete: merged via
PR #22 (`972f288`); CI green on the merge result (run 41815764073), the
`fault-library` job included, its log showing all six faults passing on Linux.
Checked on disk: `internal/isolate` imports only `internal/model` and the
standard library; the environment loader refuses a token *value*, an endpoint
carrying a scheme, port or credentials, and a health path with a query string.
The fault library found five defects in the walk itself — back-edges, an edge
blamed on its callee, elimination passed off as proof, a probe that
discriminated nothing, contract probes on templated routes — which is what it
is for. Decisions on what the run report left open:

- **The new `culprit.yaml` keys are ratified:** `environments.*.endpoints`,
  `environments.*.components.*.tokens` and an endpoint's `health_path`. The
  walk cannot place a probe without them, and they hold names and addresses,
  never values.
- **Reading a token needs a grant.** The walk reads the token from the
  environment it runs in. Inside a caller's container — the fault library
  today, an agent in Phase 33 — that is the service's own credential, which is
  what `config.read.values` exists to gate (§0.4, §2.7). The read requires
  `config.read.values` granted for that variable in that environment; without
  it the audience hypothesis is `refused` and the tree shows the branch as
  unexplored. No new capability. **First item of part 2.**
- **What establishes a symptom** — §2.8 amended. The borrowed citation stands
  for what the `symptom_of` edge asserts; the symptom's occurrence becomes a
  separate, structural attestation. **Second item of part 2**, in both
  languages and the conformance fixture, before any of it is stored.
- **`complete` is confirmed** as "nothing the walk needed went unexplored",
  not "every hypothesis tested". The report lists branches it did not need as
  untested, apart from those it needed and could not explore, and LIMITS
  states the assumption underneath: the walk stops at the first root it can
  establish, and does not look for a second, independent fault.
- **A partition seen from inside the caller is not discriminated**, because
  from there a refused connection and a stopped service look the same.
  Accepted as honest; `expected.json` says so.
- **Criteria 1 and 3 refined** as the auditor proposed (above).
- **The quickstart's synthetic `PAYMENTS_PROVIDER_KEY`** is accepted: a demo
  value the payments service now requires.

**Part 2 — the investigation in the control plane. Brief and criteria,
2026-11-04.** In this order:

1. **Carried in from part 1:** the token grant; the symptom's attestation;
   untested versus unexplored branches in the report, and the single-root
   assumption in LIMITS.
2. **The last admin cannot be removed** (the third carried-in item above).
3. **Storage.** Field 8's tables in one migration. Field 7's rule held by the
   database: a fault edge's establishing readings are a non-empty array, and
   every cited reading belongs to the same investigation (a composite key), so
   neither an empty citation nor a citation into another investigation can be
   inserted. A new role, `investigation-writer`, with INSERT on those tables
   and nothing else (invariant 3); `api-reader` gains SELECT.
4. **The API.** `POST /investigations` ingests exactly what
   `culprit diagnose --format json` writes, authenticated like the capture
   endpoints, redacted at the same choke point as a reading (invariant 11);
   `GET /investigations`, `GET /investigations/{id}` and
   `GET /investigations/{id}/tree`.
5. **The view**, built functionally on the existing component library: an
   investigations list, and the investigation with its tree, the boundary
   marked, every edge expandable to the readings that established it, the
   rubric as four booleans, untested and unexplored branches shown as such,
   and the symptom shown as reproduced or reported. `Evidence.tsx` repointed
   at readings.
6. **The correlation engine removed:** `worker/app/correlation/graph.py`,
   `job.py` and their tests, and the incident narrative job with them. The
   anomaly scorer and its impedance readings stay; the postmortem corpus and
   its editor stay.
7. **Plan correction — field 6's data migration is dropped.** An incident is
   not an investigation: it has no readings, and an investigation's edges must
   cite readings, so converting one would mean inventing them.
   `incident_candidates` and `incident_anomalies` stay read-only for one
   release — no role keeps INSERT or UPDATE on them — and the dashboard shows
   them as history from the earlier engine until Phase 34 drops them.
8. **The quickstart, README and LIMITS brought into line.** The quickstart's
   fault no longer produces an incident. It injects one the walk diagnoses
   completely — the audience mismatch is the clearest; added latency only
   ever reaches a partial diagnosis — runs `culprit diagnose` from inside the
   calling demo container as the fault library does, posts the investigation,
   and prints where to see it. Phase 31.2's standard holds: the README shows
   only what works.

**Acceptance criteria (part 2):**
- **Round trip.** The fault library's audience investigation, posted to
  `POST /investigations`, comes back from `GET /investigations/{id}/tree`
  with the same root, edges, citations, rubric and symptom attestation —
  compared whole, in a test.
- **The database holds the rule.** As `investigation-writer`, an INSERT of a
  fault edge with no establishing reading, and of one citing a reading from
  another investigation, are both refused by the database — shown by direct
  SQL in a test, not through the API. The migration round-trips (invariant 8).
- **The view.** Against the compose stack, a browser test opens the
  investigation from the list, sees the root marked, expands an edge to its
  readings, and sees the rubric as four booleans and the symptom as reproduced
  or reported — judged as Phase 31.2's criterion 4.
- **The quickstart, from a fresh clone,** ends with an investigation on the
  dashboard whose root is the fault it injected, and the README shows exactly
  that.
- **The correlation engine is gone:** nothing schedules it or the narrative
  job, no role can write the incident tables, and its tests are deleted, not
  skipped.
- **The token grant.** Without `config.read.values` for the token variable,
  the audience hypothesis is `refused` and the investigation is partial and
  says why; with it, part 1's criterion 1 still passes in the fault library.
- **The last admin.** `PATCH` and `DELETE /users/{id}` refuse with a 409, and
  the concurrent case holds.
- **`LLM_PROVIDER=none`:** diagnose, post and view are complete. With the
  narrative job gone, nothing in part 2 calls a model.

**Do NOT implement in part 2.** No `POST /investigations/{id}/probe`, and no
dashboard control that opens an investigation — both need Phase 33's agent. No
upload from the binary. No restyle (Phase 32.1). No remediation application, no
verification (`verified` stays false), no postmortem prior, no trace-id or
error-signature symptoms.

**Architecture review of part 2, 2026-11-04 — signed off, subject to one
verification.** Merged via PR #23 (`a22da56`). Every criterion was executed,
both audits found real defects and they were fixed, and the run found part 1
had broken `just quickstart` from a fresh clone — fixed, with the test that
would have caught it. Phase 32 is complete once the verification below
passes. Decisions on what the run report left open:

- **Criterion 4 was not run on the final tree.** The re-run after the audit
  fixes was killed for low memory, and the earlier run used an export of the
  working tree, not a clone. Part 1 had already broken the quickstart once
  without anyone noticing, so before Phase 32.1 starts, the quickstart is run
  from a fresh `git clone` of `main` at `a22da56`, and §5 records the result.
  If it fails, the fix goes on its own small branch first.
- **The browser test lives in a scratchpad.** Phase 32.1 adds the end-to-end
  runner (its field 11), and this test becomes its first committed journey.
- **`grants_used` is `[]` on a `token_shape` reading that read a credential**
  under `config.read.values`: the runner stamps grants from the manifest, not
  from what the probe exercised. A reading that understates its own access
  is a false record, and Phase 33's audit log is built on these fields.
  **First item of Phase 33**, with a test of `secretSource` itself.
- **`config.read.values` granted for a token also lets `culprit env capture`
  store that token.** The probe needs to read a secret in memory to inspect
  its structure; capture needs a grant to store a value. One grant now does
  both, so granting the first silently grants the second — not least
  privilege. **Phase 33, the permission-model phase:** in-memory inspection
  gets its own grant, and `config.read.values` stays the grant that stores.
- **A partial diagnosis names a subject a skimmer could read as the cause.**
  Phase 32.1: a partial diagnosis is shown as where the walk stopped and what
  it could not check, never under the word "root" or "cause" — in the view,
  the list and `culprit diagnose`'s text output.
- **The last-admin guard is in the API only.** Accepted: the API, under
  `auth-service`, is the only writer of users.
- **`queue` as a connection kind.** The root `culprit.yaml` declares two
  connections of kind `queue`, which is a component kind; the connection kind
  is `message`. Python and the database hold connection kinds to a closed set
  and would refuse the file; the Go binary accepts it. That is drift in the
  one layer allowed to exist in both languages (D1, amended), and the
  conformance fixture did not catch it because it does not cover connection
  kinds. **First item of Phase 32.1.**

---

### Phase 32.1 — Design system and the investigation-first interface

**1. Objective.** Give Culprit one coherent, premium interface, centred on
what the product does — investigations, divergences, readings — and verify it
end to end at every screen size.

**2. Why this phase exists.** `docs/PRODUCTISATION.md` §2, §4, §7 and §8.
Sequenced after Phase 32 so that the screen the product is centred on exists
before it is designed.

**3. Architectural changes.** None to the backend. The frontend gains one
design-token layer (Tailwind v4 theme variables); the existing `components/ui`
library is refined onto it; pages stop styling themselves.

**4. Components to create.**
- Tokens. Midnight black dominant; electric blue as the primary accent
  (actions, interactive elements, key data); cantaloupe orange as a sparing
  secondary accent; clean white for primary text; greys for secondary text,
  borders and depth. Status colours — the four verdicts and the four severities
  — are their own token set, never distinguished by colour alone, and orange is
  not used decoratively anywhere it could be read as a status. A type scale on
  the Inter and JetBrains Mono already installed; spacing, radius, shadow and
  surface tokens.
- Glass, restrained. Translucent, blurred surfaces for layered elements —
  navigation, dialogs, popovers, cards that sit over content — and never on
  dense data such as tables and fault trees, where readability wins.
- The component set refined: buttons, cards, form controls, navigation, the
  dialogs and tooltips already built on Radix, status indicators, and the visx
  charts.
- Every surviving route redesigned, with the Investigation view as the
  centrepiece: the fault tree with its boundary marked, every edge expandable to
  the readings that established it, and the confidence rubric shown as four
  booleans, never as a score (§2.9).
- Loading (skeletons), empty, error and success states on every data view.
- Responsive at 375, 768, 1280 and 1920 px — adapted, not shrunk. Visible focus
  states, full keyboard operation, semantic HTML, and `prefers-reduced-motion`
  honoured.
- End-to-end tests of the main journeys against the compose stack, in CI: sign
  in, open an investigation, expand an edge to its readings, read a partial
  investigation, manage settings. (Divergences have no read endpoint, so they
  get no view — field 9.) The README's screenshots are captured by the same suite at
  fixed sizes, so they can only show what works.
- Demonstration video materials following `docs/PRODUCTISATION.md` §7's five
  parts: a script, a scene-by-scene storyboard and a recording checklist, with
  the CLI segments recorded as real terminal sessions and the UI segments taken
  from the running stack. Malcolm records the narration. The README links the
  video once it exists, not before.
- Culprit annotates its own pull requests. The repository is public, so
  GitHub code scanning is free: restore the SARIF upload that `63cea12`
  replaced with an artifact (Malcolm enables code scanning in the repository
  settings), and the self-check's findings appear on the pull request — the
  thing `--format sarif` is for, shown on Culprit itself.
- A final review by an agent that has not seen the work, reading the repository
  as a recruiter and as a senior engineer would; findings fixed or listed in the
  run report.

**5. Existing components to modify.** `frontend/src/` throughout; `README.md`
(screenshots, and the video once it exists).

**6. Existing components to remove.** Styling that bypasses the tokens. Any
incident-era screen still present for Phase 32's one-release read-only period is
labelled as what it is, not restyled as if current.

**7. Interfaces/contracts.** None.

**8. Data models.** None.

**9. APIs.** None new. A view with no API behind it is not built; if a screen
seems to need an endpoint that does not exist, escalate rather than add one.

**10. Configuration.** None.

**11. Dependencies.** An end-to-end browser test runner, if the frontend has
none — the only addition expected. Any other new dependency, and in particular
a second component, chart, animation or CSS library, is an escalation.

**12. Security.** Screenshots and recordings use synthetic data only.

**13. Testing.** The end-to-end journeys above, in CI. A contrast check over
every text-and-background token pair. A gate that fails on raw colour values or
arbitrary values in page components, mutation-tested (standing invariant 10).

**14. Acceptance criteria.**
- Every page styles itself through tokens only: the gate above is green, and
  was shown red by a deliberate raw colour.
- The end-to-end journeys pass in CI, judged as Phase 31.2's criterion 4
  (refined 2026-11-04): zero console errors and failed requests on success
  paths; on deliberate error paths, only the provoked ones, each shown to the
  user.
- Every text-and-background pair meets WCAG 2.2 AA, and the main journey can be
  completed by keyboard alone.
- Every route is checked at the four widths, with screenshots in the run report.
- With `LLM_PROVIDER=none` the interface is complete: only prose summaries are
  absent, and their absence is shown plainly, not as an error.
- The README's screenshots come from the test suite.
- A partial diagnosis is shown as where the walk stopped and what it could not
  check — never under the word "root" or "cause" — in the view, the list and
  `culprit diagnose`'s text output. *(Added 2026-11-04.)*

**15. Definition of done.** Above, plus the video materials committed and
`docs/LIMITS.md` updated.

**16. Connects to next phase.** Phase 33 adds agents and grants; their settings
screen is built on this system from the start.

**17. Do NOT implement yet.** No backend feature added to fill a screen. No
marketing site. No publication. Nothing that makes a screen look complete when
the thing behind it is not.

**Carried in from Phase 32 (2026-11-04) — do these first.**
- **Connection kinds are one closed set in both languages.** The shared
  conformance fixture lists them; the Go model refuses an unknown kind, as
  Python and the database already do; the root `culprit.yaml` says `message`
  where it says `queue`. Shown red first by the fixture with `queue` in it.
- **Part 2's browser test is committed** as the first end-to-end journey,
  with the runner (field 11).
- **The partial-diagnosis wording** in `culprit diagnose`'s text output
  (field 14). The view and the list follow in part 1.

**How Phase 32.1 is run — decided 2026-11-04.** Two parts, two `/next` runs,
and Malcolm between them. The look is his call, so it is settled on the
screen the product is centred on before it is applied everywhere.

- **Part 1 — the system, on the Investigation screens.** The carried-in items;
  the tokens (colour, status, type, spacing, radius, shadow, surface) and the
  component set; the investigation list and view redesigned on them. **Part 1
  criteria:** every text-and-background token pair meets WCAG 2.2 AA (a
  checked test); the two investigation screens style themselves through tokens
  only (the gate, mutation-tested, scoped to them for now); the partial
  diagnosis criterion; `LLM_PROVIDER=none` complete; and screenshots of the
  list, a complete investigation and a partial one at 375, 768, 1280 and
  1920 px, in the run report, for Malcolm to review.
- **Malcolm reviews part 1's screenshots** and says what to change. His notes
  go into part 2's brief before it runs.
- **Part 2 — everywhere else.** Every other surviving route on the system;
  the token gate widened to every page; responsive and keyboard across all of
  them; the end-to-end journeys in CI, which take the README's screenshots;
  the SARIF upload (Malcolm enables code scanning first); the video
  materials; the fresh-eyes review last. Part 2's criteria are field 14's,
  as refined above.

**Architecture review of part 1, 2026-11-04.** Complete once PR #24
(`bd29351`) is green on the merge result and merged; `/next` checks that
before part 2 starts. Every part 1 criterion was met, both audits ran, and
the phase audit's blocking finding — a partial tree still labelled its last
edge "caused by" — was fixed in the CLI and the view, with tests over the
whole output. Decisions on what the run report left open:

- **Orange stays on a complete diagnosis's root.** Malcolm's call, on the
  screenshots: the root is the most important thing on the page, and it
  always carries the word and an icon. Red stays reserved for `fail`.
- **The stored `root_subject` of a partial diagnosis** stays, and only its
  presentation changed. Accepted, as LIMITS says. Investigations stored
  earlier keep their wording; they are records.
- **npm audit's three high advisories** (nanoid, source-map-js, vite) predate
  this branch. Part 2 touches every frontend file, so it clears them inside
  the lockfile, with no new dependency.

**Malcolm's review of the screenshots, 2026-11-04: the look is approved as
it is** — restrained, dark, orange for the root. Four changes, applied on every
screen:

1. **Dates and times are unambiguous**, in one format everywhere:
   `4 Nov 2026, 18:18` (day, month, year, 24-hour clock, local time). One
   formatter in the component set, with a unit test. No page formats a date
   itself.
2. **The investigation id leaves the top navigation bar.** It is already in
   the Symptom card.
3. **Hypotheses read as words:** "Auth audience mismatch", with the exact kind
   (`auth_audience_mismatch`) beneath it in monospace. The labels come from
   one map, and a test fails if any hypothesis kind in the shared model has
   no label — so a new kind cannot ship unlabelled.
4. **Command-line flags in prose render as code and never break across a
   line** (`--reference`).

**Part 2 — everywhere else. Brief, 2026-11-04.** Work order:

1. The four review changes, on the investigation screens.
2. Every other surviving route on the system: incidents (history),
   postmortems (list and editor), services, users, sign-in, change password,
   not found, and the command palette.
3. The token gate widened from the investigation screens to all of
   `frontend/src`, `components/ui` included (`dialog.tsx`'s `top-[20%]`).
4. Responsive at 375, 768, 1280 and 1920 px, and full keyboard operation,
   on every route.
5. npm audit's three high advisories cleared.
6. **The end-to-end suite in CI:** a job that brings up the quickstart stack
   and runs `just e2e` on every pull request. Field 14's journeys, plus every
   route loading under the refined criterion 4 of Phase 31.2. The README's
   screenshots are taken by this suite, at fixed sizes.
7. **The SARIF upload restored**, so the self-check's findings annotate
   Culprit's own pull requests. If GitHub refuses the upload because code
   scanning is not enabled on the repository, stop at that step and ask
   Malcolm to enable it; do not leave a failing step in CI.
8. The README: the interface is now shown, from the suite's screenshots, not
   just described; nothing shown that does not work (Phase 31.2's standard).
9. The video materials, following `docs/PRODUCTISATION.md` §7: script,
   scene-by-scene storyboard and recording checklist. Malcolm records.
10. The fresh-eyes review last: an agent that has not seen the work reads the
    repository as a recruiter and as a senior engineer would.

**Acceptance criteria (part 2):** field 14 as refined; the four review changes,
each with its test; the token gate covering all of `frontend/src`, shown red
by a deliberate raw colour; the e2e job green in CI on the merge result; npm
audit reporting no high or critical advisory; the SARIF upload working, or
stopped and reported as item 7 says; the README's screenshots produced by the
suite; the video materials committed.

**Do NOT implement in part 2.** No backend feature or endpoint to fill a
screen; no dashboard control that opens an investigation (Phase 33); no new
component, chart, animation or CSS library; no change to what the walk
decides; no recording of the video itself.

**Architecture review of part 2, 2026-11-05 — signed off, subject to one
record.** Merged via PR #25 (`072fb4f`). Every route on the token system, the
gate over all of `frontend/src` and shown red, contrast tested on every pair,
the four review changes each under test, browser journeys in CI, the README's
screenshots taken by them, Culprit annotating its own pull requests, and the
video materials written. The fresh-eyes review earned its place: it found the
admin password in CI logs and password field values in a failure artifact.
The one thing not on record is the run on `e97189f`, the bootstrap fix — the
only proof the quickstart and the browser journeys pass on Linux. Phase 32.2
records it first. Decisions on what the run report left open:

- **The walk's own wording** — a phase number in a rubric reason, a raw kind
  in a partial statement, machine prose in a complete one — is Phase 32.2's,
  with one label map the CLI and the frontend both read.
- **The recorded partial investigation says environment `test`**, and the
  README's list screenshot shows it. Phase 32.2.
- **The browser tour is one long test with soft assertions**, so an early
  failure hides every route after it. Phase 32.2 splits it per route.
- **Go 1.25+ is claimed; CI builds only 1.27.** The stated floor follows what
  CI builds (Phase 32.2).
- **Review screenshots are not committed from now on.** They served Malcolm's
  review; the README's own screenshots stay. `docs/review/` leaves the tree
  in Phase 32.2 (history keeps it), and later review sets go to CI artifacts.
- **The `e2e` job rebuilds every image.** Accepted as its cost for now.
- **No incident can be created any more**, so the incident panel is never
  rendered by a test. Accepted: the incident tables are dropped in Phase 34
  (field 6 of Phase 32), and the screens with them.
- **D8 no longer has an `LLM_PROVIDER=none` job** to point at — amended.

### Phase 32.2 — Close-out

**Why.** Phase 32.1 left a short list of things that are wrong or untidy
rather than missing, and the standing tasks have waited since September.
Phase 33 is the most security-sensitive phase in the plan; it should start on
a clean tree. Malcolm also decided, on 2026-11-05, to take the hosted server
offline (Phase 33, "Added 2026-11-05"), and the pipeline has to say so.

**Work order.** Two commits. The first touches hundreds of files and must be
reviewable on its own, so Claude Code stages it, writes its message file and
stops; the human commits it and says continue.
1. **First, the record.** With `gh`, confirm PR #25's final run (on
   `e97189f`) concluded success on every job, `e2e` included; put the run id
   in §5. If it did not, stop and report.
2. **Commit 1 — line endings, alone.** `.gitattributes` (`* text=auto eol=lf`, binary
   types named, anything that must stay CRLF named) and one `git add
   --renormalize .`. Nothing else in that commit.
3. **Commit 2 begins — `CLAUDE.md` under 8 KB.** What the product is now, the current
   phase and branch, the scope ceilings, the commands table, a pointer to the
   plan and the handoff. History and rules move out (`.claude/rules/` already
   holds them).
4. **The pipeline.** `deploy` runs only on `workflow_dispatch`,
   never on a push; a weekly scheduled run of the image builds and Trivy on
   `main`, which can also be started by hand, publishes nothing and deploys
   nothing; the stated Go version follows the one CI builds with (`go.mod`
   and README).
5. **The rest.** The walk's wording, from one label map in the
   shared investigation fixture that Go and the frontend both read: no phase
   number, raw kind or machine phrasing in any statement or rubric reason a
   user sees. The recorded partial investigation re-recorded with an honest
   environment name, and the README's screenshots regenerated. The browser
   tour split into one test per route. `docs/review/` removed. LIMITS,
   PERMISSIONS and INSTALL brought in line with the paused deploy.

**Acceptance criteria.**
- PR #25's final run is recorded green, `e2e` included.
- The line-endings commit is empty under `git diff --ignore-space-at-eol`, and
  every gate is green after it.
- `CLAUDE.md` is under 8 KB and contradicts nothing in handoff §1.
- On the merge of this phase, `deploy` is skipped rather than failed; the
  scheduled workflow has been started by hand once and its result is in §5.
- No user-facing text from the walk contains a phase number or a raw kind;
  the label map has one source, and a kind with no label fails a test in both
  languages; the fault library still finds the same roots, 7 of 7 — the
  wording changes, the verdicts do not.
- One deliberately broken route fails only its own browser test.
- Nothing references `docs/review/`.

**Do NOT.** No feature work, nothing from Phase 33, no change to what the walk
decides — only what it says.

**Architecture review, 2026-11-05 — signed off.** On `main` as `2e05980` and
`2e187fc`: run 42083753833 green on every job with `deploy` skipped, and the
scheduled images workflow, started by hand, green and publishing nothing
(42084489435). Checked on disk: `CLAUDE.md` is 5.2 KB; `.gitattributes` sets
`* text=auto eol=lf`; `deploy` runs only on a hand-started `workflow_dispatch`
on `main`; the images workflow runs Mondays at 04:17 UTC. Every standing task
from September is closed. Decisions:

- **Q17, ruled.** Keep, exactly as they are, the identifiers a user can look
  up or act on: probe ids (the names in `docs/PROBES.md` and on the command
  line), grant names (an instruction to grant something is only usable if it
  names the grant exactly), and reading and hypothesis ids (the interface
  shows each beside what it names). Wherever the interface shows one, render
  it as code. Replace what is notation rather than a name: an arrow pair in a
  sentence becomes "from order-service to inventory-service". Done in Phase 33
  part 1, which rewrites the refusal text anyway.
- **Phases land on `main` through a pull request.** 32.2 reached `main` by a
  direct push past the "Protect Main" ruleset, so `main` changed before any
  check ran on it. The push run afterwards was green, so nothing was lost this
  time. Recorded in the handoff's protocol. The ruleset should refuse a direct
  push from anyone: Malcolm removes himself from its bypass list, or limits
  his bypass to pull requests (his setting).
- **The local quickstart cannot migrate with Malcolm's `infra/.env.prod`**,
  which predates four writer roles. Phase 33 part 2 builds against a local
  control plane, so before it runs, the local file is regenerated
  (`scripts/bootstrap_env.py --local --force`) and the local quickstart's
  volume recreated. It holds only demo data. This supersedes the 31.1 note
  about copying seven saved passwords in.

---

### Phase 33 — The production agent and the permission model

**1. Objective.** A deployable, least-privilege, auditable agent that lets an
investigation reach a running production system.

**2. Why this phase exists.** Probe value scales with network position; adoption
scales inversely with access demanded. This phase is where that trade is made
explicit and safe, and it is deliberately late — the product is already useful
without it.

**3. Architectural changes.** The `culprit` binary gains an `agent` subcommand.
Agents pair with the control plane over an outbound-only connection, so no
inbound port is opened in the user's production network.

**4. Components to create.**
- `cli/cmd/culprit agent` — long-lived mode, capability enforcement, audit log,
  probe execution, outbound-only transport.
- `api/app/agents/` — registration, pairing, grant management, audit ingestion.
- Deployment recipes: Docker, Compose sidecar, Kubernetes DaemonSet, systemd.
- `frontend/src/routes/SettingsAgents.tsx` — grants shown in plain language, with
  a visible diff when a grant changes.

**5. Existing components to modify.** `infra/docker-compose.prod.yml` gains an
optional agent. A new `agent-reader` Postgres role, per invariant 3.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** Agent↔control-plane protocol is versioned and
capability-scoped. A control plane cannot ask an agent to do anything the agent's
local config has not granted — **the agent is the authority on its own
capabilities, not the server.** This matters: a compromised control plane must
not be able to escalate.

**8. Data models.** `agents`, `agent_grants`, `agent_audit_log` (append-only).

**9. APIs.** `POST /agents/register`, `GET /agents`, `PATCH /agents/{id}/grants`,
`POST /agents/{id}/tasks`, `GET /agents/{id}/audit`.

**10. Configuration.** Agent config is a local file the operator writes, listing
grants explicitly. There is no "grant all" value; the parser rejects wildcards.

**11. Dependencies.** None new beyond the optional cloud adapters from Phase 30.

**12. Security.** The most security-sensitive phase in the plan.
- Outbound-only; no inbound listener.
- Agent-side capability authority (above).
- Append-only audit log of every probe, its grants, and its target.
- Mutual TLS with per-agent credentials, rotatable, revocable — and unlike the
  Phase 26 bug, revocation is tested for immediate effect.
- Threat model documented in `docs/SECURITY.md`, explicitly covering a
  compromised control plane and a compromised agent.

**13. Testing.** Grant-escalation tests. Revocation-immediacy test. Audit
completeness test asserting every executed probe produced a log entry. A chaos
test where the control plane requests an ungranted capability and the agent
refuses.

**14. Acceptance criteria.**
- An agent with only `net.dns.resolve`, `net.tcp.connect`, `net.tls.inspect`,
  `net.http.outbound` and `config.read.names` can complete a reachability
  investigation and visibly cannot complete a schema one. *(Grants named
  2026-11-06: the configuration parser refuses wildcards, `net.*` included.)*
- Revoking a grant takes effect on the next task, with no restart.
- The audit log accounts for every probe run.
- Agent container is under 30 MB and runs as non-root with a read-only filesystem.

**15. Definition of done.** Above, plus `docs/SECURITY.md` and a documented
minimum-viable grant set for each investigation class.

**16. Connects to next phase.** Verification needs to re-run probes in the
environment where the fault was found.

**17. Do NOT implement yet.** No write capabilities. No remediation execution. No
multi-tenant control plane — one install still serves one team.

**Added 2026-11-03 (Phase 31 review) — readings are written with the agent's
own credential.** Four write endpoints accept `CULPRIT_PROJECT_TOKEN` today:
`POST /readings`, `/facts/captures`, `/divergences/captures` and
`/model/captures`. That costs nothing while one CI job holds the token for all
four; it becomes a hole the day a probe runner sits on a production host, which
is this phase. **Acceptance criterion added:** `POST /readings` accepts an
agent's credential and nothing else; a reading's `agent_id` is taken from that
credential, never from the request body; and the project token is scoped to the
three capture endpoints. If something other than an agent writes readings by
then, it gets its own scoped credential, not the project token.

**Added 2026-11-04 (Phase 32 review) — first two items.**
- **`grants_used` records what a probe exercised**, not only what its manifest
  declares: a `token_shape` reading that read a credential under
  `config.read.values` names that grant. The audit log this phase builds is
  only as true as these fields. `secretSource` gets a test of its own.
- **Inspecting a secret is not storing it.** A probe that reads a secret in
  memory to inspect its structure gets its own per-key grant; it permits no
  storage, by capture or anywhere else. `config.read.values` remains the
  grant that lets a value be stored. Granting one never implies the other.

**Added 2026-11-05 — no hosted deployment before or during this phase.**
Malcolm decided to take `culprit-vm` offline rather than repair it: it had
served an unpatched, pre-Phase-14 API publicly since August. This phase builds
and proves the agent against a local control plane, with the agent in a
separate Compose network that can reach the control plane only outbound — the
same arrangement CI can run, which a VM never was. "Deploy must be green by
Phase 33" (2026-09-12) is superseded. A hosted demo comes back when Culprit is
published, through the existing runbook (handoff §4, VM remediation).

**How Phase 33 is run — decided 2026-11-05.** Where this block and the fields
above differ, this block wins.

**Three parts, three `/next` runs, an architecture review after each.** This is
the most security-sensitive phase in the plan. The transport is not built
until the agent's authority over itself has been proven without one.

- **Part 1 — the agent, standing alone.** The carried-in items; `culprit agent`
  running tasks from a local source; its configuration, its authority over its
  own grants, its audit log; its container image. No transport, no
  control-plane change, no migration, no interface.
- **Part 2 — the agent meets the control plane.** Pairing, per-agent
  credentials, the task transport, revocation, audit ingestion, readings and
  investigations written under the agent's credential, the project token
  scoped down, and the API able to open an investigation by handing a symptom to
  an agent — the dashboard's control for it moved to part 3 (2026-11-06). Proven against a local control plane, with the agent in
  its own Compose network that reaches the control plane only outbound.
- **Part 3 — the operator's surface.** The agents settings screen, the
  dashboard control that opens an investigation through an agent, the
  deployment recipes, `docs/SECURITY.md`, the minimum grant set for each
  investigation class, and README, LIMITS and PERMISSIONS brought in line.

Parts 2 and 3 get their criteria at the review before each.

**Decisions.**
- **Per-agent credentials are Ed25519 keys that sign every request, not mutual
  TLS.** Field 12 says mutual TLS. The control plane sits behind Caddy, so a
  client certificate would be checked at the proxy and reach the API as a
  header the API has to trust — a new trust boundary in front of the one that
  matters. A signed request is verified by the API itself and needs nothing
  from the proxy, and it gives everything field 12 asks for: per agent,
  rotatable (a new key), revocable (the key is withdrawn and the next request
  is refused), and testable in Go and Python alike. The agent generates its key
  and never sends the private half. Pairing is a one-time code the operator
  copies from the dashboard, which registers the public key. Each request signs
  its method, path, a digest of its body, a timestamp and a nonce; the API
  refuses a stale timestamp or a repeated nonce. Still over TLS. The binary
  already signs capture envelopes with Ed25519.
- **The agent is the authority on its grants; the control plane can only
  narrow them.** Field 9's `PATCH /agents/{id}/grants` cannot widen anything.
  The grants an agent uses for a task are its local configuration's grants
  intersected with the allowance the control plane sends with that task. A
  compromised control plane can withhold a grant; it cannot add one. The agent
  re-reads its configuration before every task, so a grant removed on either
  side takes effect on the next task with no restart (field 14).
- **The audit log is append-only twice over.** The agent writes each entry to
  a local, hash-chained, append-only file before it returns the result, so an
  edited or deleted entry is detectable. Part 2 ships the entries to
  `agent_audit_log`, which no role can update or delete — a database rule,
  not a convention. An entry records the task, the probe, the target, the
  grants exercised and the verdict.
- **One new package may reach the network.** Part 2's transport lives in
  `cli/internal/transport`, added to the D8 allowlist beside `probe` and
  `capture`, and it talks only to the control-plane address in the agent's
  configuration.
- **What a task can be:** run a named probe on a target, or run the walk for a
  symptom. The walk runs in the binary (D1 and D2, amended); the control plane
  stores the tree that comes back. `POST /investigations/{id}/probe`, and a
  dashboard control that opens an investigation, arrive in part 2, as tasks.
- **Who writes what, after part 2.** `POST /readings` accepts an agent's
  credential only, and `agent_id` comes from the credential (2026-11-03).
  `POST /investigations` accepts an agent's credential or the project token —
  CI still posts what `culprit diagnose` writes — and records which. The
  project token keeps the three capture endpoints and that one, nothing else.

**Part 1 — the agent, standing alone. Brief and criteria, 2026-11-05.**

**Work order.**
1. **Carried in, first.**
   - `grants_used` records what a probe exercised (2026-11-04); `secretSource`
     gets tests of its own.
   - Inspecting a secret is not storing it (2026-11-04). The new per-key grant
     is **`config.inspect.values`**: a probe may read the value in memory to
     inspect its structure, and nothing may store or emit it.
     `probe.auth.token_shape` needs it, and `config.read.values` no longer
     satisfies it; `config.inspect.values` never lets capture store a value.
     The shared model's grant list, the generated catalogue mirror,
     `docs/PERMISSIONS.md` and the walk's refusal text follow.
   - Q17 as ruled at 32.2's review: no arrow pair in a sentence.
2. **`culprit agent`**, a long-lived subcommand that takes tasks from a source
   behind an interface: in this part, a local directory the tests write to; in
   part 2, the transport.
3. **Its configuration**, a local file listing grants explicitly per
   environment. The parser refuses a wildcard, `all`, or an unknown grant
   name, naming the line. Re-read before every task.
4. **Its authority.** A task needing a grant the configuration does not give
   is refused before anything is dialled, and the refusal is both a reading
   and an audit entry.
5. **Its audit log**: append-only, hash-chained, one entry per task and per
   probe, written before the result is returned.
6. **Its image**: the static binary on a scratch or distroless base.

**Acceptance criteria (part 1).**
- A `token_shape` reading that read a credential names `config.inspect.values`
  in `grants_used`; a refused reading names no grant it did not use.
  `secretSource` has tests of its own.
- With only `config.read.values` granted, `token_shape` is refused; with only
  `config.inspect.values`, `culprit env capture` stores no value for that key.
- The configuration parser refuses a wildcard, `all` and an unknown grant,
  each with its line.
- A task asking for an ungranted capability is refused without dialling — a
  test counts dials on a fake network — and is recorded (field 13's chaos
  test, against the local source).
- A grant removed from the configuration takes effect on the next task, with
  no restart.
- Every executed probe has exactly one audit entry, and editing or deleting an
  entry is caught by the chain check.
- The agent image is under 30 MB, runs as a non-root user, and runs with a
  read-only root filesystem — checked in CI.
- No arrow pair in the walk's user-facing text, added to 32.2's wording test.

**Do NOT implement in part 1.** No transport and no client to the control
plane. No change to `api/`, `worker/`, the database or the frontend, except the
generated catalogue mirror and the shared model's grant list. No deployment
recipe beyond the image. No write capability.

**Architecture review of part 1, 2026-11-06 — signed off.** Merged via PR #27
(`57541e3`), CI green on the merge result (reported by Malcolm; the run id is
recorded by part 2's first step). Checked on disk: the D8 allowlist still names
only `probe` and `capture`, and `internal/agent` takes its probe runner through
an interface rather than importing `probe`. Every criterion was executed by the
tests and again by `phase-auditor` against the real binary; the invariant
auditor found a CI-only failure in the image check that Docker Desktop hid, and
it was fixed before merge. Decisions:

- **Field 14's `net.*`** is the four network grants by name (reworded above).
- **Stale records.** The recorded investigations, one browser assertion and
  the README's partial screenshot still show `config.read.values` and
  `token_shape` v2. Part 2 re-records them first.
- **The rename breaks a user's `culprit.yaml`** that granted
  `config.read.values` for a token. LIMITS says so; `docs/UPGRADING.md` does
  not yet. Part 2 adds it.
- **`process.exec.allowlist` is recorded when authorised, not after the
  command ran.** Accepted: an audit record that may overstate access errs the
  safe way; one that understates it does not.
- **`POST /investigations/{id}/probe` is dropped.** A stored investigation is
  a final record (Phase 32.1); appending readings to it would make it mutable.
  Probing again is a new task, and diagnosing again a new investigation. This
  supersedes the decision above that it arrives in part 2.
- **The dashboard control that opens an investigation moves to part 3**, with
  the rest of the operator's surface, so part 2 is backend and binary only —
  the security-critical part, reviewed without interface changes beside it.

**Part 2 — the agent meets the control plane. Brief and criteria, 2026-11-06.**

**Work order.**
0. **Record part 1's CI run** (PR #27's merge result) in §5. Then regenerate the
   local `infra/.env.prod` and recreate the local quickstart volume, as 32.2's
   review required — its demo data is lost, and that is accepted.
1. **Carried in.** Re-record `api/tests/data/investigations/`
   (`CULPRIT_FAULT_LIBRARY_RECORD`), the browser assertion and the README's
   partial screenshot under `config.inspect.values`; add the rename to
   `docs/UPGRADING.md`.
2. **The signing contract, first**, as `Reading`'s was: the canonical request
   (method, path, body digest, timestamp, nonce), Ed25519 verification, and a
   conformance fixture Go and Python both read — a valid request; then a
   tampered body, a changed path, a stale timestamp, a replayed nonce, a wrong
   key and a revoked key, each refused.
3. **Storage.** Agents, single-use pairing codes (stored hashed), allowances,
   tasks, seen nonces and `agent_audit_log`. A new role per write surface
   (standing invariant 3). No role holds UPDATE or DELETE on
   `agent_audit_log`, and a trigger refuses both even to the owner.
4. **The API.** Pairing code (admin), registration, list, allowances (narrow
   only), tasks (admin), and the agent's own endpoints: claim its next task,
   post a result, post audit entries. A claim is atomic, and an agent can
   claim only tasks addressed to it. Readings under the agent's credential;
   investigations under either credential, recording which; the project token
   scoped down (the decision above).
5. **The binary.** `culprit agent init` (writes the key `0600`, never
   overwrites one) and `culprit agent pair`; `cli/internal/transport` as the
   agent's task source, added to the D8 allowlist.
6. **CI.** The two-network topology and the end-to-end scenario below.
7. LIMITS, PERMISSIONS, UPGRADING (the project token's narrower scope breaks
   any CI that posts readings with it).

**Defaults.** A request older than 300 seconds is refused, and nonces are kept
at least that long. A pairing code expires after 15 minutes and works once. A
newly paired agent's allowance is empty: the operator grants explicitly, and
only from what the agent reports it holds. The API's refusal of a bad request
does not say which check failed.

**Acceptance criteria (part 2).**
- Every case in the signing fixture behaves as written, in Go and in Python.
- A pairing code works once and not after it expires; every byte the agent
  sends while pairing is captured, and no private key is in it.
- Revoking an agent refuses its very next request; removing a grant from its
  allowance takes effect on its next task — neither needs a restart.
- An allowance naming a grant the agent does not report holding, a wildcard,
  or `all` is refused with 422. A task whose allowance names a grant the
  agent's configuration lacks runs without it, refused and recorded — field
  13's chaos test, over the real transport.
- `POST /readings` accepts only an agent's credential; `agent_id` is the
  credential's, a body naming another agent is refused, and the project token
  is refused.
- A test lists every route and the credentials each accepts: the project
  token works on exactly the three capture endpoints and `POST /investigations`,
  and adding it to any other route turns the test red.
- A stored investigation records whether an agent or the project token
  submitted it.
- Every probe the CI scenario runs has exactly one `agent_audit_log` row. The
  API refuses an entry that does not extend that agent's stored chain. No
  role, the owner included, can update or delete a row — shown red by
  removing the trigger.
- In CI, the agent shares no Compose network with the control plane and
  reaches it only through its published address. A test fails if anything in
  `cli/` calls a listen function. `internal/transport` dials only the
  configured address and follows no redirect, and it is the allowlist's third
  package, mutation-tested.
- End to end in CI: an investigation opened through the API is run by an agent
  with the four network grants and `config.read.names` — a reachability
  investigation completes, a schema one is visibly partial and names
  `db.metadata.read`. The audience fault, run by an agent holding
  `config.inspect.values`, still roots at the audience.
- The migration round-trips with agents, tasks and audit rows present.
- `LLM_PROVIDER=none` changes nothing.

**Do NOT implement in part 2.** No frontend change: the agents screen and the
dashboard control that opens an investigation are part 3's. No deployment
recipe beyond the CI topology, and no `docs/SECURITY.md` (part 3). No mutual
TLS, no write capability, no multi-tenancy, no hosted deployment, no
`POST /investigations/{id}/probe`.

**Q18 ruled, 2026-11-10 — `infra/.env.prod` is plaintext by design, and it is
created private.** CodeQL's `py/clear-text-storage-sensitive-data` (alert #1,
`scripts/bootstrap_env.py`) is right that the file holds secrets in clear text.
That is its purpose: Compose's `env_file` reads plain `KEY=VALUE`, and every
value is a credential a service has to present, so hashing or encrypting it at
rest would only move the key somewhere equally plain. So it is not a false
positive: it is an accepted, documented storage decision. Two consequences:

- **The real weakness beside it is fixed.** The file was written and only then
  set to `0600`, so on first creation the secrets were briefly readable by
  other local users. It is now written to a temporary file created `0600` in
  the same directory (`tempfile.mkstemp`), flushed, and moved into place with
  `os.replace`, so it never exists with wider permissions, and an existing
  file's mode is never relied on. A test checks the temporary file's mode
  before it is moved into place.
- **The alert is dismissed as "Won't fix", by Malcolm, after the fix is on
  the branch** — never before, because the comment states the fix as fact. If
  the fix's analysis closes or replaces the alert, the new one gets the same
  treatment. LIMITS says the same thing in plain words.

The new CVE in the frontend image (`golang.org/x/net` v0.60.0, fixed in
v0.62.0) is ambient — published after the last green run — and is fixed by
bumping the pin in its own commit (pattern 3: fix it, never weaken the gate).

**Architecture review of part 2, 2026-11-10 — signed off.** Merged via PR #28
(`58e7593`), with every pull-request check green, the code-scanning check
included, after Q18's ruling. Criteria 8 to 10 ran only in CI, so they were
checked there: the `e2e` job runs `just agent-e2e` with no condition and no
`continue-on-error`; the recipe sets `CULPRIT_AGENT_E2E=1`; the `-run`
pattern names a test that exists, so it cannot pass with "no tests to run";
a missing setting fails the test rather than skipping it; and the test
asserts the reachability, schema and audience outcomes and the audit rows.
Both audits found real defects, fixed before merge: a replay window at the
edge of nonce cleanup, and `agent-admin` holding a read it never used.
Decisions:

- **`/ci` now gates on every pull-request check and on open code-scanning
  alerts** (`c43a508`). Accepted. Its first report had called a red pull
  request green from the workflow runs alone.
- **Plain `http` for `control_plane.url`** is in LIMITS, and CI needs it to
  reach the control plane at `host.docker.internal`. The decision of record
  says "still over TLS". **Part 3:** the agent refuses a plain-`http` URL
  unless the host is a loopback address or the configuration sets an explicit
  `allow_plain_http`, which the agent reports at every start and which no
  shipped recipe sets.
- **A malformed body gets 422 before 401** on the agent routes, so an
  unauthenticated caller can probe the schema, and the body is parsed before
  anyone is authenticated. **Part 3, first:** the signature is checked over
  the raw body before the body is parsed.
- **The local `infra/.env.prod` and quickstart volume were not regenerated**:
  the permission system refused both to Claude Code. They are Malcolm's to
  run before part 3, which needs a working local stack.
- **The schema investigation's database** lives in the agent's own copy of the
  model, not in `demo-services/culprit.yaml`. Accepted: adding it there would
  have turned the fault library's audience walk partial.
- **`api-reader`'s SELECT on the four new tables** is argued in the migration,
  as `c4e8a1f2b3d5`'s was. Accepted under standing invariant 3.

**Licence — decided by Malcolm, 2026-11-06.** Culprit is AGPL-3.0-only.
`extractors/python`, `extractors/node` and `shared/` are Apache-2.0: they run
inside other people's projects or define the protocol, and the Python
extractor depends on `culprit-shared`, so `shared/` cannot be copyleft without
making the extractor copyleft too. The copyright line stays as LICENSE has it.
Everything published before the change remains available under MIT. It lands
as its own pull request, before part 3 — not inside a phase.

**Part 3 — the operator's surface. Brief and criteria, 2026-11-10.**

**Work order.**
0. **Preconditions, not part of the run:** the licence pull request has merged,
   and Malcolm has regenerated the local `infra/.env.prod` and recreated the
   quickstart volume.
1. **Carried in, first:** the signature checked before the body is parsed;
   plain `http` refused as above; and the quickstart's admin step, which
   prompts for a password when a person runs it from a terminal (found by
   Malcolm, 2026-11-10). `docker compose run` gives the bootstrap container a
   terminal whenever the caller has one, and `create_user`'s `getpass` then
   reads that terminal instead of the piped password. Every automated run had
   no terminal, so none saw it. Reproduce it first under a pseudo-terminal
   (`script`), then fix it (`run -T`).
2. **The agents screen** (admin only): every agent with its status, when it
   last made a request, the grants it reports and its allowance; create a
   pairing code, shown once; edit an allowance, with the change shown as a
   diff before it is saved; revoke, after confirmation.
3. **Opening an investigation through an agent**: choose an agent and a
   symptom; the task's progress shows; the investigation opens when it lands.
   When no agent reports the grants a symptom needs, the control says so
   rather than failing.
4. **The minimum grant set for each investigation class** — reachability,
   schema, auth and audience, configuration — in `docs/PERMISSIONS.md`.
5. **Deployment recipes** in `deploy/agent/`: Docker, Compose, Kubernetes and
   systemd. Non-root, read-only root filesystem, the key mounted as a secret
   with mode `0600`, an `https` control plane.
6. **`docs/SECURITY.md`**: the threat model for a compromised control plane, a
   compromised agent, a leaked pairing code, a leaked agent key, a leaked
   project token and a replayed request — what each can and cannot do.
7. **A link to the source in the dashboard**, which AGPL-3.0 §13 makes easy
   to honour for anyone who runs a modified copy.
8. README, LIMITS, PERMISSIONS and UPGRADING brought in line.

**Acceptance criteria (part 3).**
- On every agent route, a request that is unsigned or badly signed is refused
  401 before its body is parsed — a malformed body included.
- `just quickstart`, run under a pseudo-terminal, completes with no prompt
  and creates the admin from `infra/.env.prod` — shown failing before the fix.
- The agent refuses a plain-`http` control plane except to a loopback address
  or with `allow_plain_http`, which it reports at every start; no recipe sets
  it.
- Every action on the agents screen is a browser journey in CI: create a
  pairing code and see a real agent appear; change an allowance, see the
  diff, save it; revoke, and see the agent's next request refused. A member
  sees "This page is for admins".
- Opening an investigation from the dashboard runs end to end in CI with a real
  agent, and the investigation opens. With no agent holding the needed
  grants, the control explains why and starts nothing.
- For each investigation class, a test runs it with exactly its documented
  grant set (complete), then with each grant removed in turn (partial, naming
  that grant).
- The Compose recipe is the one CI runs. The Kubernetes manifest becomes
  Ready in CI's kind cluster, as a non-root user with a read-only root
  filesystem. The systemd unit passes `systemd-analyze verify`. No recipe
  allows plain `http`.
- Every "cannot" in `docs/SECURITY.md` names the test that enforces it, and a
  check fails if a named test does not exist.
- The new screens style themselves through tokens only (the gate covers
  them), work at the four widths with keyboard alone, and their screenshots
  are in the run report for Malcolm.
- `LLM_PROVIDER=none` changes nothing.

**Do NOT implement in part 3.** No write capability, no new probe, no hosted
deployment, no multi-tenancy, no mutual TLS, no change to how the walk runs.

**Architecture review of part 3, 2026-11-10 — signed off; Phase 33 is
complete.** Merged via PR #31 (`e125b4b`), every pull-request check green with
no open code-scanning alert; the licence change (PR #30) landed before it.
Checked on `main`: the CI workflow runs `check_security_doc.py`, the agent
recipes in the kind cluster, and the quickstart under `script`. The Kubernetes
recipe ran for the first time in CI, went red twice and was fixed with
diagnostics rather than weakened. Decisions:

- **Q19 — accepted, narrowed.** `api-reader` may read when each agent last made
  a signed request, but not the nonce values: the grant becomes a column grant
  on `agent_nonces (agent_id, seen_at)`, and a test shows `api-reader` cannot
  select `nonce`. **First item of Phase 34 part 2** (part 1 has no migration).
- **Kubernetes is a one-replica Deployment, not a DaemonSet.** Accepted: one
  key is one identity and one audit chain, and two agents must not share a log.
  An agent per node needs a key per node — later, if ever.
- **The key Secret is `0640 root:65532` under `fsGroup`.** Accepted; it is the
  closest Kubernetes allows a non-root reader, and LIMITS says so.
- **The dashboard gates on the reachability set only**, and a walk needing more
  ends partial naming the grant. Accepted.
- **The agent exits when its control plane is unreachable**, and the recipes'
  restart policies bring it back. Accepted for now; a crash loop during a long
  outage is noisy, and LIMITS says so.
- **The Compose journey's agent joins the demo services' network** to probe
  them, and reaches the API only through its published address; part 2's
  separate-network scenario still runs. Accepted.
- **The new screens' screenshots** are in run 42805541738's `e2e-screenshots`
  artifact, not committed. Malcolm's notes on them, if any, go into Phase 34
  part 2.

---

### Phase 34 — The verification loop and calibration

**1. Objective.** Close the loop: after a change, determine whether the fault is
actually resolved, and record the outcome so accuracy becomes measurable.

**2. Why this phase exists.** "I think this is the problem" is where every
competitor stops. Verification is what makes the diagnosis trustworthy, and the
outcome record is the only honest source of an accuracy number — which is the
strongest single claim this product could ever make.

**3. Architectural changes.** Investigations gain a lifecycle beyond diagnosis.
Readings gain expiry semantics that matter.

**4. Components to create.**
- `cli/internal/verify/` — re-runs the **full** reading set from the original
  diagnosis, not just the failing probe.
- `api/app/outcomes/` — outcome recording, per-fault-class accuracy aggregation.
- `culprit verify <investigation-id>`.

**5. Existing components to modify.** `investigations` gains
`verification_status`. The confidence rubric (§2.9) gains its `verified` flag.

**6. Existing components to remove.** `incident_candidates`,
`incident_anomalies` and their root-cause columns — superseded by
`investigations` since Phase 32 and now migrated. `worker/app/memory/link_job.py`'s
30-minute substring heuristic is replaced by a proper change→divergence link,
since deploy metadata is now captured.

**7. Interfaces/contracts.**

```
Verification
  investigation_id
  applied_change      -- commit sha, image digest, or config capture id
  reran               [reading_id]
  failing_now_passes  bool
  no_regressions      bool     -- every previously-passing reading still passes
  verdict             verified | not_resolved | inconclusive | changed_underneath
  verified_at
```

**Naive verification is confidence theatre**, which the vision explicitly rules
out. Re-running only the failing probe produces false confirmations from caching,
intermittency, or an unrelated change. Verification therefore requires all three:
the failing probe now passes, every previously-passing probe still passes, and
the change that was applied is identified. If the environment changed in ways not
attributable to the applied change, the verdict is `changed_underneath`, not
`verified`.

**8. Data models.** `verifications`, `outcomes`.

**9. APIs.** `POST /investigations/{id}/verify`, `GET /outcomes/accuracy`.

**10. Configuration.** `culprit.yaml` gains `verify:` — reference environment,
regression tolerance.

**11. Dependencies.** None new.

**12. Security.** Verification runs the same probes under the same grants. No new
surface.

**13. Testing.** Fault library extended: inject fault → diagnose → apply the
known fix → verify, asserted end to end for every fault class. A negative test
where the "fix" does not fix it and verification must say so. A test where an
unrelated change occurs mid-verification and the verdict must be
`changed_underneath`.

**14. Acceptance criteria.**
- Every fault in the library completes the full detect→diagnose→fix→verify cycle
  in CI.
- A deliberately wrong fix produces `not_resolved`.
- `GET /outcomes/accuracy` reports a real per-fault-class number derived from
  recorded outcomes, not an estimate.

**15. Definition of done.** Above, plus the accuracy number published in the
README, with its methodology and its sample size stated.

**16. Connects to next phase.** A verified fault tree is what the narrator and the
agent surface consume.

**17. Do NOT implement yet.** No automatic remediation. Culprit still recommends;
the human or the coding agent applies.

**How Phase 34 is run — decided 2026-11-10.** Where this block and the fields
above differ, this block wins.

**Two parts, two `/next` runs, an architecture review after each.**
- **Part 1 — the loop, in the binary.** `culprit verify`, the `Verification`
  model, the verdict rules, and the fault library carried through
  inject → diagnose → fix → verify for every fault class. No API, no
  migration, no interface.
- **Part 2 — outcomes in the control plane.** Verifications stored and shown,
  verification as an agent task, outcomes and `GET /outcomes/accuracy`, the
  README's number with its methodology. Its criteria are written at part 1's
  review.

**Decisions.**
- **Investigations stay final.** A verification is its own append-only record
  that points at an investigation. Whether an investigation is verified is
  derived from its latest verification and never written back into it, so
  field 5's `verification_status` column and any edit to the stored rubric are
  dropped; the view shows the rubric's `verified` from the verification.
- **The full reading set, measured again.** Verification re-runs every probe
  the investigation ran — same targets, same grants, same vantage — and never
  reuses a stored reading. A probe that cannot run now makes the verdict
  `inconclusive`, never `verified`.
- **Five verdicts, a closed set.**
  - `verified` — every reading that failed now passes on two consecutive runs,
    every reading that passed still passes, and every difference between the
    environment before and after is explained by the change named.
  - `not_resolved` — a reading that failed still fails.
  - `regressed` — the failing readings pass, but one that passed now fails. Not
    in field 7's list; added because "the fix broke something else" is the
    most actionable thing verification can say.
  - `changed_underneath` — the failing readings pass, but the environment
    changed in a way the named change does not explain.
  - `inconclusive` — anything else: a probe refused or inconclusive now, a
    result that flips between the two runs, no change named, or no record of
    the environment before.
  A `verified` verification cannot be constructed unless all three of its
  clauses hold — enforced on the type, in Go and Python.
- **"Before" is recorded at diagnosis.** From part 1, `culprit diagnose`
  records an environment capture with every new investigation whose grants
  allow one, and the investigation says when they do not. Investigations
  stored before this phase have no before, so their verifications can reach
  `inconclusive` at best on that clause.
- **What the change explains.** `--change` names what was applied: an image
  for a component, a config key for a component (repeatable), or a commit.
  Before and after are compared with the engine `culprit diff` already uses; a
  difference is explained when it falls on a subject the named change touches.
  Anything else is `changed_underneath`.
- **The accuracy number is honest about its sample** (part 2). It is computed
  only from recorded outcomes, per fault class, with its count. Outcomes from
  the fault library are planted faults, and the README says exactly that; it
  never presents them as accuracy on real systems until real outcomes exist.
- **Field 6 is dropped.** Phase 32 dropped the incident-to-investigation
  migration as unsound, so removing `incident_candidates` and
  `incident_anomalies` would delete history, not migrate it; they stay,
  read-only. The change-link job serves only that history; it is left alone,
  and the named change is verification's link from a change to a fault.

**Part 1 — the loop, in the binary. Brief and criteria, 2026-11-10.**

**Work order.**
1. The `Verification` model in `culprit_model`, Go and Python, with a
   conformance fixture both read, written first — `verified` unconstructible
   without its three clauses.
2. `culprit diagnose` records the before capture, or says why it could not.
3. `cli/internal/verify/` and `culprit verify`: re-run, compare, judge. It
   takes a probe runner through an interface, as `isolate` does, so the D8
   allowlist does not change.
4. The fault library: a known fix for each fault class, and the loop asserted
   end to end in its CI job.
5. LIMITS, PROBES and README for what `culprit verify` does and does not do.

**Acceptance criteria (part 1).**
- The conformance fixture's cases hold in Go and in Python, including a
  `verified` with one clause false, which neither can construct.
- `culprit verify` re-runs exactly the probes the investigation ran — the
  count is asserted — and reuses no stored reading.
- For every fault class in the library: inject, diagnose, apply the known fix,
  verify — `verified`, in CI.
- A wrong fix gives `not_resolved`.
- A fix that resolves the fault but breaks a previously passing probe gives
  `regressed`.
- An unrelated change between diagnosis and verification — a config key
  changed on another component — gives `changed_underneath`.
- A result that flips between the two runs gives `inconclusive`; so does no
  change named, and so does an investigation with no before capture.
- The D8 allowlist is unchanged, and `LLM_PROVIDER=none` changes nothing.

**Do NOT implement in part 1.** No API, no migration, no interface, no agent
task kind, no accuracy aggregation, no README number. No automatic
remediation: Culprit verifies a change someone else applied.

---

### Phase 35 — The agent surface and the narrator

**1. Objective.** Make Culprit a tool an AI coding agent calls, and constrain the
narrator to rendering settled facts.

**2. Why this phase exists.** The separation the vision describes — coding agent
proposes, diagnostic engine adjudicates — only exists if the engine is callable
and the narrator cannot invent. Both are true only after there is something real
to call and to narrate, which is why this is last.

**3. Architectural changes.** The existing MCP server is repointed from
engineering memory to the diagnostic surface. The narrator becomes the sole LLM
call in the system, structurally unable to create facts.

**4. Components to create.**
- New MCP tools: `culprit_diagnose`, `culprit_probe`, `culprit_check`,
  `culprit_explain_connection`, `culprit_verify`, `culprit_system_model`.
- `worker/app/narrate/` — replaces `worker/app/rag/job.py`'s role. Input is a
  settled fault tree; output is prose plus a remediation suggestion. It receives
  no raw telemetry and cannot request more.

**5. Existing components to modify.** `mcp_server/tools.py` gains the new tools;
the four memory tools are retained — file history and coupled files remain
genuinely useful to a coding agent. `worker/app/rag/prompts.py` is rewritten for
narration rather than hypothesis generation.

**6. Existing components to remove.** `worker/app/rag/job.py`'s
hypothesis-generation path, superseded by isolation.

**7. Interfaces/contracts.** MCP tool responses carry the fault tree, the
readings, the confidence rubric and a verification procedure — the shape the
vision's example transcript describes. Every response is structured; the prose
field is optional and clearly labelled as derived.

**8. Data models.** None new.

**9. APIs.** MCP tools as above. The existing AST no-LLM test is extended to the
new tools — they retrieve and execute probes; they never call a model.

**10. Configuration.** `LLM_PROVIDER=none` remains fully supported and is a CI
job.

**11. Dependencies.** None new.

**12. Security.** MCP stays stdio-first and single-tenant. A coding agent calling
`culprit_probe` is bound by the same grants as any other caller — an agent cannot
acquire capability by asking.

**13. Testing.** A test asserting the narrator's output contains no subject,
reading or verdict absent from its input fault tree. This is the structural
guarantee that the LLM cannot invent, and it is the most important test in the
phase.

**14. Acceptance criteria.**
- A coding agent, given a failing checkout flow, calls `culprit_diagnose`,
  receives a rooted fault tree with evidence, applies a change, calls
  `culprit_verify`, and receives `verified`.
- The narrator, given a fault tree, produces prose citing only what is in it.
- Removing the LLM entirely leaves every tool functional except the prose field.

**15. Definition of done.** Above, plus a recorded end-to-end demonstration of the
agent loop against a real fault.

**16. Connects to next phase.** None — this plan ends here. Anything beyond is a
new plan document.

**17. Do NOT implement yet.** No write-capable MCP tools. No agent-initiated
remediation. No multi-tenancy.


**Added 2026-11-04.** A narrator failure — a missing key, a provider error, a
timeout — is recorded as a status the interface shows, never a permanent
`pending`. The incident copilot's narrative job never did this
(`docs/LIMITS.md`).

---

## §4. Explicitly out of scope for this entire plan

Stated so a future session does not quietly widen the boundary:

- **Any `mutate`-effect probe**, synthetic write transaction, or `*.write`
  capability. Adding one requires its own plan document.
- **Automatic remediation.** Culprit diagnoses and recommends. Something else
  changes the system.
- **Business-logic correctness** (§0.1, Tier 3). Culprit reports where intent is
  un-cross-checkable; it does not judge whether the rule is right.
- **A whole-codebase semantic model** (D6).
- **Multi-tenancy.** One install, one team, unchanged from the prior plans.
- **Kafka.** Redis Streams remains the transport.
- **Trained anomaly models.** The EWMA scorer stays statistical.
- **A general observability platform** — no log search, no metric graphing, no
  tracing UI. Culprit diagnoses; it does not store everything you send it.
- **Row-level database reads by default.** Metadata only, unless explicitly and
  narrowly granted.

## §5. How we will know this worked

The standard the vision sets is the right one, and it is testable. Three
measures, in order of importance:

1. **The fault library passes.** Every injectable fault produces the correct root
   subject, and a deliberately wrong fix fails verification. Run in CI on every
   push from Phase 32 onward.
2. **A stranger's project.** `culprit check` finds at least one real, confirmed
   fault in a project neither authored nor controlled by us, with a
   false-positive rate low enough that the finding is believed. Required from
   Phase 29.
3. **A published accuracy number.** Derived from recorded outcomes (Phase 34),
   with methodology and sample size stated. No competitor in this space currently
   publishes one.

And the negative test that keeps the whole thing honest, which runs from Phase 29
to the end:

> With `LLM_PROVIDER=none`, `culprit check`, `culprit diff`, `culprit probe`,
> `culprit diagnose` and `culprit verify` all produce complete, correct output.
> Only the prose is missing.

If that ever stops being true, the product has become the thing it was built not
to be.

---

## §6. Assumptions this plan makes

Stated explicitly so they can be corrected rather than discovered.

- **Python and TypeScript are the first target ecosystems.** They are what the
  repository already contains and what the author knows. Go and Ruby extractors
  are community-shaped work, not phase work.
- **The author is willing to maintain a small Go codebase.** If not, revisit D2
  before Phase 28 begins — the fallback is documented there.
- **This is being built as a real product, not primarily as a portfolio
  artefact.** If the priority is a portfolio piece, reorder: Phase 31 and 32 are
  the impressive ones and Phase 30 could be deferred. Say so before Phase 28
  starts, because the ordering below optimises for a usable product early.
  *(2026-11-03: still product first. The portfolio requirements are folded in
  as Phases 31.2 and 32.1, not by reordering.)*
- **Single-tenant, single-VM deployment remains acceptable** through Phase 35.
