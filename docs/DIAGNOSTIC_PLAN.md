# Culprit — Diagnostic Engine Plan (Phases 26–35)

Written 2026-09-08. Companion to, and successor of, `docs/IMPLEMENTATION_PLAN.md`
(Phases 0–12), `docs/SELF_HOSTED_PLAN.md` (Phases 13–20) and
`docs/AI_NATIVE_PLAN.md` (Phases 21–25). Same convention as those documents:
read §1 (invariants) plus the specific phase section you are working on, not
the whole file.

**Phase 25 (memory visualisation) is cancelled.** It was never built and the
new direction supersedes it. Do not implement it.

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
3. Least privilege per job. Add a role, never widen one.
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
- Blocking the network path between two containers flips exactly the reachability
  probe to `fail` while both components' own health probes stay `pass` — the
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
- Injecting an auth-audience mismatch between two demo services produces an
  investigation whose root subject is the audience config, not the 500 at the
  edge.
- The fault tree distinguishes symptom, propagation and root, and every edge
  cites readings.
- Isolation on a 6-hop chain uses `O(log n)` probes, not `n` — asserted by
  counting probe executions in the test.
- `LLM_PROVIDER=none` produces a complete, correct fault tree. Only the prose
  summary is absent.

**15. Definition of done.** Above, plus the fault library running in CI on every
push.

**16. Connects to next phase.** Phase 33 lets this run against production.

**17. Do NOT implement yet.** No remediation *application* — Culprit recommends,
it does not change the user's system. No verification loop yet. No production
agent.

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
- An agent with only `net.*` and `config.read.names` can complete a reachability
  investigation and visibly cannot complete a schema one.
- Revoking a grant takes effect on the next task, with no restart.
- The audit log accounts for every probe run.
- Agent container is under 30 MB and runs as non-root with a read-only filesystem.

**15. Definition of done.** Above, plus `docs/SECURITY.md` and a documented
minimum-viable grant set for each investigation class.

**16. Connects to next phase.** Verification needs to re-run probes in the
environment where the fault was found.

**17. Do NOT implement yet.** No write capabilities. No remediation execution. No
multi-tenant control plane — one install still serves one team.

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
- **Single-tenant, single-VM deployment remains acceptable** through Phase 35.
