# Culprit — Performance Conformance Plan (Phases 36–39)

Written 2026-11-11. Successor to `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35), which
ends at Phase 35 and says anything beyond it is a new plan document. Same
conventions: read §1 here plus the phase being worked on. **Every standing
invariant in `DIAGNOSTIC_PLAN.md` §3, and D1–D8 with their dated amendments,
hold in every phase below.** Phase 36 starts only after Phase 35 is complete.

Each phase gets a "How Phase N is run" block and its parts at the review before
it, as Phases 32 to 35 did.

---

## §0. Where the original sketch needs correcting

The sketch held since 2026-11-03 was: *N+1 queries, a missing index confirmed by
`EXPLAIN ANALYZE`, unbounded queries, unpaginated list endpoints, bundle
composition from the build metafile, fetch waterfalls — static analysis
proposes, a probe confirms, the planner explains, a verification probe proves
the fix.* The loop is right. Five things in it would produce a worse product if
built literally.

### §0.1 Slow is not a fault until something declares fast

A latency with nothing to compare it to has no INTENT to diverge from. "Usually
120 ms, now 400 ms" is the baseline-as-truth mistake `DIAGNOSTIC_PLAN.md` §0.2
exists to stop. It is also why the walk finds no failing reading for the fault
library's latency fault, which therefore verifies as `inconclusive` (Q21,
2026-11-10).

**Correction.** A performance finding is a divergence between a **declared
budget** (INTENT) and a **measurement** (OBSERVED). Where nothing declares a
budget, Culprit lists the surface as unbudgeted — as Phase 29's
unverifiable-surface report lists subjects nothing cross-checks — and never
invents a threshold on the user's behalf.
The impedance scorer's baseline still only ranks hypotheses.

### §0.2 `EXPLAIN ANALYZE` runs the query

`ANALYZE` executes the statement: against production rows, with production
cost. That breaks `DIAGNOSTIC_PLAN.md` §0.4 — database metadata, never rows —
and puts load on the system being diagnosed.

**Correction.** The planner is asked with `EXPLAIN (GENERIC_PLAN)` (PostgreSQL
16 and later), which plans a parameterised statement and executes nothing.
What it gives is an estimate, and it is used as one: the measurement comes from
`pg_stat_statements` (OBSERVED), the explanation from the planner, and the
reference from the declared budget. `EXPLAIN ANALYZE` is unrepresentable in the
probe layer (Phase 37).

### §0.3 "Static analysis proposes" must not become a code model

Inferring N+1 or unbounded queries from ORM code means reconstructing queries
and loops from source: the whole-codebase model D6 rules out, and the analyser
that sinks the project (`DIAGNOSTIC_PLAN.md` §0.5).

**Correction.** Static proposals use only what extractors already see at an
interface — a route's declared response shape, the build's own manifest. N+1
is measured from statements per request (Phase 39), never inferred from source.

### §0.4 A latency probe must not become load

Measuring latency means sending requests. Enough of them, in parallel, is a
load test against someone's production.

**Correction.** A fixed, small, capped number of sequential `GET` (or
`OPTIONS`) requests, spaced, per run — the HTTP client already refuses every
other method. No configuration raises the cap. Load testing is out of scope
for this plan (§4).

### §0.5 Fetch waterfalls need a browser where the user's frontend runs

A waterfall is a property of a page loading in a browser. The binary has no
browser, and the fault library's Playwright is Culprit's own test harness, not
a vantage in a user's system.

**Correction.** Out of scope for this plan (§4).

---

## §1. Decisions

### P1 — Budgets are INTENT facts

`culprit.yaml` gains `budgets:` — subject, predicate, value, why — read as
INTENT facts at rank 100, beside `invariants:`. An OpenAPI operation's
`x-culprit-budget` extension is read at rank 80. The predicates are a closed
set, grown one phase at a time: `latency_p50_ms`, `latency_p95_ms` (36);
`query_mean_ms_max` (37); `bundle_gzip_bytes_max`, `response_items_max` (38).
Two sources declaring different budgets for one subject is an
`intent_conflict`, as for any other fact.

### P2 — Measuring is statistical; judging is a pure rule

A latency or timing reading records how many samples were taken, how many
succeeded, the percentiles and the spread. The verdict is a pure function of
those and the budget — **fail** when even the favourable bound of the measured
percentile is over budget, **pass** when even the unfavourable bound is within
it, **inconclusive** between, when the spread is too wide, or when too few
samples succeeded. The rule lives in `culprit_model` in Go and Python with a
conformance fixture both read, as `Reading`, `Investigation` and
`Verification` do. `inconclusive` is expected and honest, not a defect.

### P3 — A slow hop is found by subtraction, not guessed

The walk measures each hop from its own vantage — A to B from where A sits, B
to C from where B sits — and roots at the hop whose own time breaks its budget
while the hops downstream of it keep theirs. Where a vantage cannot be placed,
the branch is unexplored and the diagnosis partial, as for partitions today.

### P4 — The database is read through statistics and plans, never rows

Two new read capabilities. **`db.stats.read`** — `pg_stat_statements`,
`pg_stat_user_tables`, `pg_stat_user_indexes`. **`db.plan.read`** —
`EXPLAIN (GENERIC_PLAN, FORMAT JSON)` and nothing else. The database source
sends only statements from a closed set of templates — catalogue reads,
statistics reads and that one form of `EXPLAIN` — and refuses anything else
before it is sent. Planning a statement needs `SELECT` on the tables it names,
and reading another role's statement text needs `pg_read_all_stats`, so the
recommended agent role holds both and PERMISSIONS says what they reveal.
`db.rows.read` stays separate, is not implied, and Culprit never sends a
statement that returns a row. Normalised statement text passes through the
redaction choke point (standing invariant 11).

### P5 — A database finding joins the planes

A statement over its budget (OBSERVED against INTENT), the planner showing a
sequential scan filtered on a column (the explanation), the live schema with
no index on that column (CONFIGURED), and the migrations declaring none
(INTENT): one root, `missing_index`, citing all four. Verification names the
migration that adds the index; the planner then shows an index scan and the
statement's time is within budget. `pg_stat_statements` is cumulative, so
timings are deltas between two snapshots — never a reset, which would be a
write. A window with no calls is `inconclusive`.

### P6 — Build budgets belong to `culprit check`

A bundle needs no running system. The Node extractor reads Vite's build
manifest and the files it names, and reports each entry's raw and gzip size as
OBSERVED facts in the environment `build`; a budget over them is a finding in
`culprit check`, in CI, beside Phase 29's.

### P7 — N+1 only where it can be seen cleanly

Statements per request are exact only when nothing else talks to the database.
An environment can declare `isolated: true`; only there is a per-request
statement count evidence, filtered to that database and role. Elsewhere the
probe is `inconclusive`, saying why. Trace ingestion, which would let shared
environments be measured, is not built by this plan.

### P8 — The demo grows a database

The demo services hold no data today, and the fault library's database faults
run against Culprit's own quickstart database. Planting a slow query in
Culprit's own tables would be Culprit testing itself by breaking itself.
Phase 37 gives inventory-service a small database of its own — a separate
database in the quickstart's Postgres, with its own role — declared in
`demo-services/culprit.yaml` as a database component, as that file's header
already anticipates. Phases 37 and 39 plant their faults there.

---

## §2. Additions to the core model

- **Budget fact.** `plane: INTENT`, a subject, a predicate from P1's closed
  set, an integer value, provenance (`culprit.yaml` rank 100, or a spec
  extension rank 80).
- **Timing reading.** `measured`: sample count, successes, p50, p95, spread;
  never a body, header value or row.
- **Plan reading.** `measured`: node types, relation names, filter columns and
  estimated rows; never a parameter or constant.
- **Index fact.** CONFIGURED from `pg_indexes`; INTENT from the migration
  reader, which learns `create_index` and `drop_index`.
- **Hypotheses.** `latency_budget_exceeded` (connection, component),
  `statement_budget_exceeded`, `missing_index`, `n_plus_one`.
- **Capabilities.** `db.stats.read`, `db.plan.read`. Neither is a write.
  §2.7's rule stands: no `*.write` capability exists.

---

## §3. The phases

### Phase 36 — Latency budgets, and a walk that can see slow

**1. Objective.** Let a declared latency budget be the reference a measurement
diverges from, and let the walk find which hop is slow.

**2. Why this phase exists.** Every fault class in the library closes the loop
except latency: nothing declares how fast is fast, so the walk finds no
failing reading and verification lands `inconclusive` (Q21). It is the fault a
small team meets most often in production, and the one Culprit cannot yet
finish.

**3. Architectural changes.** Budgets join INTENT. A probe measures latency and
is judged by a rule shared by Go and Python. The walk gains latency hypotheses
and localises by subtraction across vantages (P3).

**4. Components to create.**
- `budgets:` in `culprit.yaml`; `x-culprit-budget` read from OpenAPI.
- `probe.http.latency`: n sequential requests, spaced, `GET` (or `OPTIONS` for
  a route that is not `GET`), under `net.http.outbound`; `cost: metered`.
- The latency rule in `culprit_model`, Go and Python, and its conformance
  fixture, written first.
- `latency_budget_exceeded` on connections and components in the walk.
- The fault library's latency fault, given a budget; its known fix (the
  injected delay cleared) is an `action`.

**5. Existing components to modify.** `cli/internal/isolate`,
`cli/internal/verify`, the manifest loaders in Go and Python, the demo's
`culprit.yaml`, PROBES, PERMISSIONS, LIMITS.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** Budget fact and timing reading as §2. The rule's
inputs are the samples and the budget; its output is a verdict and a reason.

**8. Data models.** None new: budgets are facts, timings are readings.

**9. APIs.** None.

**10. Configuration.** `budgets:`. The sample count and spacing are bounded
(for example 10 to 50 requests, at least 50 ms apart); no setting lifts the cap.

**11. Dependencies.** None new.

**12. Security.** `GET` and `OPTIONS` only, as the HTTP client already enforces;
no body or header value kept; a hard cap on requests per run, enforced in the
probe, not the configuration.

**13. Testing.** The fixture; the probe against a fake server with controlled
delays; the walk's subtraction on a synthetic three-hop chain; the fault
library end to end.

**14. Acceptance criteria.**
- The latency rule's fixture holds in Go and Python, including a spread wide
  enough to be `inconclusive`.
- Against a fake server: well under budget passes; well over fails; straddling
  or noisy is `inconclusive`; too few successes is `inconclusive`.
- On a synthetic chain A → B → C with C slowed, the walk roots at the hop into
  C and records A → B as propagation, never as root.
- With a budget declared, the library's latency fault diagnoses with a root and
  verifies `verified` after its known fix; without one it still verifies
  `inconclusive`, saying no budget is declared.
- No configuration makes the probe send more than its cap in a run — a test
  tries.

**15. Definition of done.** Above, plus PROBES, PERMISSIONS, LIMITS and the
README's tour showing a budget.

**16. Connects to next phase.** Phase 37 applies budget-and-measure to the
database.

**17. Do NOT implement yet.** No load generation. No percentiles from
telemetry: impedance stays a baseline that ranks. No threshold Culprit chooses
for the user.

**How Phase 36 is run — decided 2026-11-11.** Where this block and the fields
above differ, this block wins.

**Two parts, two `/next` runs, an architecture review after each.**
- **Part 1 — budgets and the measurement.** Budgets become INTENT facts, the
  latency rule exists in both languages, and `probe.http.latency` measures.
  `culprit check` and `culprit probe` can see slow; the walk cannot yet.
- **Part 2 — the walk sees slow.** Latency hypotheses, localisation,
  verification, and the fault library's latency fault closing (Q21). Its
  criteria are written at part 1's review.

Phase 35's close-out lands first. Part 1's step 0 confirms it.

**Decisions — where the fields predate the build.**
- **`GET` only; `OPTIONS` is dropped** (fields 4 and 12). CORS middleware
  answers an `OPTIONS` request before any handler runs, so its time says nothing
  about `POST /orders`. A read-only probe cannot time a route that is not `GET`.
  For a budget on one, the probe sends nothing and is `inconclusive`, saying
  so. `HEAD` is not added: the HTTP client's method allowlist is unchanged.
- **No probe presents a credential in this phase.** A budget on a route that
  needs a token would only measure the refusal, so it is `inconclusive` ("the
  route answered 401"). Presenting a token from `token_env` would be a new way
  for a secret to leave the binary. It is decided on its own, at part 2's
  review if the walk needs it, and not slipped into a latency probe. LIMITS says
  which budgets this leaves unmeasurable.
- **The rule is integer arithmetic on order statistics** (P2, made exact).
  - Samples are whole microseconds.
  - A percentile is the nearest-rank order statistic, never interpolated.
  - Its bounds are the order statistics at the ranks the exact binomial gives
    for 90% confidence on each side, computed in integers.

  There is no floating point anywhere in the rule, so Go and Python cannot
  disagree in a last digit. The confidence level is one constant, stated in
  LIMITS.
- **"The spread is too wide" (P2) means the interval straddles the budget.**
  There is no separate width threshold: any width limit would be a number
  Culprit chose (§4). One consequence follows from the arithmetic, not from a
  choice. At 90%, a p95 can be shown within budget only from 45 samples
  (1 − 0.95ⁿ ≥ 0.9 needs n ≥ 45), so a p95 budget can pass only near the cap.
- **The sample count and spacing are not configurable** (field 10 refined). The
  probe sends 50 requests for a p95 budget and 20 for a p50, at least 50 ms
  apart. 50 is a hard cap in the probe. With nothing to set there is nothing to
  lift, and nobody can configure a p95 check that could never pass.
- **A sample is a `2xx` answer or a timeout.** A `401` or a `500` measures a
  refusal, not the route, so it is not a sample, and too few samples is
  `inconclusive`. A request that does not answer in time counts as slower than
  the budget. Dropping it would report a service that has stopped answering as
  fast. The per-request timeout is set above the budget, and the probe's own
  timeout bounds the whole run.
- **What one sample measures is fixed and recorded.** It is one request on a
  new connection, timed from dialling to the last byte of the response, with
  connection setup recorded separately. A client that pools sees less, and the
  reading says what it measured. Part 2 needs the setup time to tell the hop
  from the component.
- **The reading carries the rule's inputs** (field 7): every sample, and the
  budget in `expected` with its `expected_source`. The verdict is then a pure
  function of the reading alone. Go's `Reading.Validate` and Python's reading
  model each refuse a latency reading whose verdict the rule does not give, so
  the API refuses one wherever a reading arrives. This makes the check
  structural, as Phase 34's re-judged verifications are.
- **A budget must point at something.** `culprit check` reports a budget whose
  subject no other INTENT source declares; otherwise a mistyped route would
  never be measured and nothing would say so. The unbudgeted surface is listed
  only when the manifest declares `budgets:` at all, so a project that has not
  opted in is not told that every route lacks one.
- **One budget for every environment.** Budgets are INTENT, so a CI runner is
  held to the same number as production. LIMITS says so.
- **The demo declares its budget on inventory-service's `GET /ready`.** Its
  `why` says this is the route the walk already asks, because it passes through
  the fault middleware. The route order-service actually calls, `GET /stock`,
  needs a token in the faults stack (see above). The value is set well clear of
  both the healthy time and the injected 800 ms, and the run report says how it
  was chosen.
- **One vantage per walk (P3 corrected, for part 2).** A walk runs in one binary
  (D1 amended) and sends no probe to an agent elsewhere, so "B to C from where B
  sits" is not available. Part 2 bisects on requests sent from this vantage to
  each component on the request path. The root is the deepest component over its
  budget whose callees keep theirs. The connection setup that part 1 records
  separates the hop from this vantage from the component itself. Anything only
  another vantage could see is unexplored, and the diagnosis is partial. Part
  2's brief restates field 14's synthetic chain on that basis.
- **Carried in from Phase 35.** Part 2's first item limits narration parity's
  time rule to measured values and minted ids. A declared budget that differs
  between the legs is a difference, shown red.

**Part 1 — budgets and the measurement. Brief and criteria, 2026-11-11.**

**Work order.**
0. Confirm that `main`'s push run on the close-out's merge is green, with
   `e2e (none)`, `e2e (stub)` and `narration-parity` included. If the close-out
   is not merged, stop. If a job failed on the runners' network, re-run it. If a
   test failed, stop and escalate.
1. Write the latency rule and its conformance fixture in `culprit_model`, Go
   and Python, before any probe exists.
2. Add budgets:
   - `budgets:` in `culprit.yaml` (rank 100), read by the Go loader and by the
     API's manifest model;
   - `x-culprit-budget` on an OpenAPI operation (rank 80);
   - the predicates `latency_p50_ms` and `latency_p95_ms`, and no others yet.

   Two sources that disagree go through the comparator as an `intent_conflict`.
   A budget on an undeclared subject is reported. The unbudgeted surface is
   listed when `budgets:` is declared.
3. Build `probe.http.latency` as decided above, taking its budget from
   expectation resolution (Phase 31.1). Classify its address input, so that
   `culprit mcp` binds it.
4. Validate readings by the rule in Go and Python, and therefore in the API.
5. Add the demo's budget, and run the probe in the fault-library job. It fails
   with the latency fault injected and passes once the fault is cleared. The
   library's expected verdicts do not change.
6. Update the documents:
   - PROBES;
   - PERMISSIONS: what the probe sends, and that no new capability is needed;
   - LIMITS: everything decided above that a user would trip over;
   - the README's `culprit.yaml` reference: `budgets:`. The tour waits for
     part 2.

**Acceptance criteria (part 1).**
- The rule's fixture holds in Go and Python, with the same verdicts and
  reasons. It includes these cases:
  - well under the budget;
  - well over;
  - straddling (`inconclusive`);
  - too few samples (`inconclusive`);
  - a timeout counted as slow, where dropping it would pass;
  - the floor: a p95 that cannot pass from 44 samples and can from 45.

  It is shown red by moving a bound one rank.
- Against a fake server with controlled delays, counting requests at the
  server:
  - well under the budget passes;
  - well over fails;
  - straddling is `inconclusive`;
  - mostly `401` or `500` answers are `inconclusive`;
  - a request past its timeout counts as slow.
- No input, configuration or manifest makes the probe send more than 50 requests
  in a run, or space them less than 50 ms apart. A test tries each, counting at
  the server.
- A budget on a route that is not `GET` is `inconclusive`, with no request sent
  (counted). The probe never sends `OPTIONS`, `HEAD`, a body or a credential.
- Through `culprit mcp`, the probe's address input refuses an undeclared
  endpoint before dialling (counted). `TestEveryCatalogueInputIsClassified`
  covers the probe.
- In `culprit check`:
  - two sources with different budgets for one route give an `intent_conflict`;
  - a budget on a route nothing else declares is reported;
  - an unknown predicate is refused by the Go loader, by the Python model and by
    the API's manifest model.
- A latency reading whose verdict disagrees with its own samples and budget is
  refused by Go validation, by Python validation and by the API. Each refusal
  is shown red.
- In CI's fault-library job, on Linux, `culprit probe probe.http.latency` on
  inventory-service's `GET /ready` fails with the latency fault injected and
  passes once it is cleared.
- From a fresh `git clone`, the quickstart starts with the demo's `budgets:` in
  `culprit.yaml`. A manifest field the API's model did not know has broken a
  fresh clone before.
- Every pull-request check is green, both `e2e` legs and `narration-parity`
  included. `LLM_PROVIDER=none` changes nothing.

**Do NOT implement in part 1.**
- No walk change: no latency hypothesis, no change to verification, no change
  to the fault library's expected verdicts.
- No credential sent by any probe.
- No `OPTIONS` or `HEAD`.
- No parallel requests, no configurable count, no load.
- No percentile other than p50 and p95.
- No percentiles from telemetry.
- No threshold that Culprit chooses. The demo's budget is the demo's own
  declaration, with its `why`.

**Added 2026-11-12, at the review of Phase 35's close-out.**
- **Step 0 is met.** `main`'s push run 43167772415 on `08f7d65` (PR #36's
  merge) passed every job, including both `e2e` legs and `narration-parity`.
  Record it; nothing needs re-running.
- **One item joins the work order after step 0 (Q25).** Add a test that only
  `probe.BuiltIn` calls `Catalogue.Register`, and show it red by adding a
  registration elsewhere. `culprit mcp` binds the address inputs it knows by
  name. The test holds that every probe an agent can run is one whose inputs are
  classified. `probe.http.latency` joins the catalogue through `BuiltIn`, like
  every other probe.

---

### Phase 37 — The database: statements, plans and indexes

**1. Objective.** Find a statement over its budget, explain it with the
planner, and tie it to an index the migrations never declared — without
reading a row.

**2. Why this phase exists.** The query that was fine at a hundred rows is the
commonest performance fault in a small team's stack, and the one where every
plane meets (P5).

**3. Architectural changes.** Two read capabilities (P4). Index facts in
capture and in the migration reader. A closed set of statement templates the
database source cannot step outside.

**4. Components to create.**
- `db.stats.read` and `db.plan.read`, in the model, the catalogue, PERMISSIONS
  and the agent's configuration parser.
- The template set, and a refusal before sending for anything outside it.
- `probe.db.statement_budget`: the delta mean time per normalised statement
  over a window; `inconclusive` with no calls in it.
- `probe.db.plan`: the planner's shape for one statement.
- Index facts, live and declared.
- `statement_budget_exceeded` and `missing_index` in the walk.
- The demo's database (P8), with a seeded table and migrations of its own.
- A fault in the library: an inventory-service list endpoint filtering an
  unindexed column of that table, with traffic from the load generator; the
  known fix is a migration adding the index (a `commit` change).

**5. Existing components to modify.** `internal/capture` (indexes), the
migration reader, `isolate`, `verify`, `demo-services/culprit.yaml`,
inventory-service, the load generator, the quickstart's Postgres (loading
`pg_stat_statements` if the image does not already), PERMISSIONS, LIMITS.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** Statement facts carry normalised text, redacted.
Plan readings as §2.

**8. Data models.** None new.

**9. APIs.** None.

**10. Configuration.** `query_mean_ms_max` on a database or one of its tables.

**11. Dependencies.** `pg_stat_statements` in the target, documented; without
it, `inconclusive` saying so.

**12. Security.** The template set is the boundary: a test sends an arbitrary
statement and an `EXPLAIN ANALYZE`, and both are refused before they leave the
binary. `db.plan.read` does not imply `db.rows.read`. No reading holds a
constant from a statement.

**13. Testing.** Template refusals; plan parsing over recorded plans; index
facts from a live database and from migrations; the library end to end.

**14. Acceptance criteria.**
- Nothing outside the template set reaches the database, `EXPLAIN ANALYZE`
  included.
- With the index missing, the walk roots at `missing_index` on that column,
  citing the statement's time against its budget, the plan's sequential scan,
  the live schema and the migrations.
- After the migration adding the index, named as the change, verification
  lands `verified`; with an index on the wrong column, `not_resolved`.
- Without `db.plan.read` the diagnosis is partial and names it; without
  `pg_stat_statements`, `inconclusive` saying so.
- A statement holding a secret-looking constant leaves no trace of it in any
  reading.

**15. Definition of done.** Above, plus PERMISSIONS' recommended agent role for
the database, and LIMITS.

**16. Connects to next phase.** Phase 38's bounds need no database at all.

**17. Do NOT implement yet.** No `EXPLAIN ANALYZE`. No index created, and no
query rewritten, by Culprit: it names the column and the evidence. No row read.

**Carried in (2026-11-12, at the review of Phase 35's close-out).** This comes
before anything reads statement text. `redact_credentials` misses
`password=…`, Slack tokens and `user:pass@host` (Phase 35 close-out, F2). Widen
it at the choke point, in Go and in Python, with a conformance case for each.
P4 sends normalised statement text through this function, and a connection
string or a password literal in a statement is exactly what it must catch.

---

### Phase 38 — Bounds: what the browser downloads, and what a list returns

**1. Objective.** Two bounds a small team breaks without noticing: the size of
the frontend's bundles, and the length of what a list endpoint returns.

**2. Why this phase exists.** Both are cheap to check deterministically, and the
bundle check needs no running system — it belongs in `culprit check`, in CI.

**3. Architectural changes.** The Node extractor reads the build (P6). A probe
counts items and keeps nothing else.

**4. Components to create.**
- Bundle facts from Vite's build manifest and the files it names: each entry's
  raw and gzip size, and its largest chunks.
- `bundle_gzip_bytes_max`, judged in `culprit check`.
- `probe.http.response_items`: one `GET`; counts the items of the response's
  array (top level, or at a declared JSON pointer); keeps the count only.
- The unbounded surface: list routes whose declared response is an array and
  which declare no paging parameter — listed, as Phase 29's unverifiable
  surface is, not reported as findings.

**5. Existing components to modify.** `extractors/node`, `culprit check`'s
report, the HTTP probes, README, LIMITS.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** Bundle facts in the environment `build`; the items
reading's `measured` is a count.

**8. Data models.** None.

**9. APIs.** None.

**10. Configuration.** `bundle_gzip_bytes_max` per entry;
`response_items_max` per route.

**11. Dependencies.** None new.

**12. Security.** The items probe reads structure, never values — a test with
secret-looking items checks the reading holds none.

**13. Testing.** Recorded build outputs; a fake server; Culprit's own
frontend's real build in CI, through the root `culprit.yaml`, as the self-check
already runs.

**14. Acceptance criteria.**
- `culprit check` reports an entry over its gzip budget, naming its largest
  chunks; under budget it reports nothing; with no build present, a "Not
  checked" line says so.
- A route returning more items than its bound fails, within passes, and a
  response that is not an array is `inconclusive`.
- Over a recorded spec holding paged and unpaged list routes, the unbounded
  surface names exactly the unpaged ones.
- No reading holds an item's value.

**15. Definition of done.** Above, plus the README showing a bundle budget in
CI.

**16. Connects to next phase.** Phase 39 measures what an unbounded list costs
the database per request.

**17. Do NOT implement yet.** No browser, no fetch-waterfall analysis, no
response values kept.

---

### Phase 39 — N+1, where it can be seen cleanly

**1. Objective.** Find a request that issues one statement per item, in an
environment where nothing else is talking to the database.

**2. Why this phase exists.** N+1 is the canonical ORM performance fault. A
static guess at it is a code model (D6); measured per request it is exact —
where the measurement is clean (P7).

**3. Architectural changes.** An environment may declare `isolated: true`.

**4. Components to create.**
- `probe.db.statements_per_request`: one `GET` to a list route, bracketed by
  two `pg_stat_statements` snapshots and an item count; a statement run at
  least once per returned item is the N+1. Needs `db.stats.read` and
  `net.http.outbound`; in an environment not declared isolated,
  `inconclusive`, saying why.
- `n_plus_one` on the route, citing the statement and the counts.
- A fault in the library: an inventory-service list route over the demo's
  database (P8) that loads a relation per item; its known fix loads them
  together (a `commit` change).

**5. Existing components to modify.** The manifest loaders (`isolated:`),
`isolate`, `verify`, LIMITS.

**6. Existing components to remove.** None.

**7. Interfaces/contracts.** The reading's `measured`: the item count and, per
normalised statement, its calls in the window.

**8. Data models.** None.

**9. APIs.** None.

**10. Configuration.** `isolated: true` on an environment.

**11. Dependencies.** None new.

**12. Security.** As Phase 37's template set; no new statement.

**13. Testing.** Recorded statistics; the library end to end in CI, with the
load generator paused for the probe's window — it reaches the demo's database
through inventory-service, under the same role, so while it runs the
environment is not isolated and must not be declared so.

**14. Acceptance criteria.**
- In an isolated environment, the N+1 route is found with its statement and
  counts named; the fixed route passes.
- In an environment not declared isolated: `inconclusive`, saying so — never a
  guess.
- Verification after the fix lands `verified`.

**15. Definition of done.** Above, plus LIMITS on why shared environments are
not measured.

**16. Connects to next phase.** None in this plan.

**17. Do NOT implement yet.** No trace ingestion; `telemetry.traces.read` stays
unused. No analysis of ORM source. No N+1 detection in a shared environment.

---

## §4. Explicitly out of scope for this entire plan

- **Load testing**, and any probe that sends more than its cap.
- **`EXPLAIN ANALYZE`**, and any statement that returns a row.
- **Automatic remediation** — creating an index, rewriting a query, changing a
  bundle. Culprit names the cause and verifies a change someone else applied.
- **Fetch waterfalls**, and anything else that needs a browser in the user's
  system.
- **Trace ingestion.**
- **Thresholds Culprit invents.** A budget is declared by the user or it does
  not exist.

## §5. How we will know this worked

The fault library's latency fault, given a budget, verifies `verified` where it
verifies `inconclusive` today; it gains a missing index and an N+1; and each is
diagnosed with its root and verified after its known fix, in CI, on every
push. `culprit check` stops an oversized bundle in CI before it ships, and a
list endpoint over its bound fails its probe. `LLM_PROVIDER=none` changes
nothing. And the README's accuracy number grows to include the new faults,
still labelled as planted faults.

## §6. Assumptions this plan makes

- **PostgreSQL 16 or later** for `EXPLAIN (GENERIC_PLAN)`. The quickstart runs
  `timescaledb-ha:pg16`, so it holds there; on an older server the plan probe
  is `inconclusive`, saying why.
- **`pg_stat_statements` is loaded** in the target. Whether the quickstart's
  image preloads it is unconfirmed; Phase 37's first item checks, and the
  quickstart turns it on if not.
- **Vite** builds the frontends Phase 38 reads, with `build.manifest` on.
  Culprit's own `vite.config.ts` does not set it today; Phase 38 does. Other
  bundlers are extractor work, not phase work.
- **Bundle sizes are OBSERVED**, measured from a build, in the environment
  `build` — not CONFIGURED, which is reserved for what an environment is set up
  to do.
