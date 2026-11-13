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

**Architecture review of part 1, 2026-11-12 — signed off; the gate is `main`'s
push run.** PR #37 was merged as `716205f`. I read the checks from GitHub's API.
The pull request's last run, 43182997513 on `e169fcc`, passed every job. The
run before it, 43181751008 on `3be789e`, passed every job too, including both
`e2e` legs, `narration-parity` and the fault library.

Checked on disk:
- The rule's arithmetic is integer-only. The only floats are whole-number JSON
  inputs, which are accepted, as Go accepts them.
- `latency_conformance.json` holds the six named cases, the 44/45 floor, and a
  sample exactly on the budget.
- The probe caps itself at `LatencyMaxRequests`, whatever its inputs say.

The phase-auditor's work is the reason to trust this part. It recomputed every
rank from n = 1 to n = 50 with exact fractions. It fuzzed Go against Python on
40,000 inputs and found no differences. It found two criteria NOT MET on the
first build:
- `-p x -p x` sent 100 requests 0.1 ms apart;
- a `url` input made a `POST` budget send timed `GET`s.

Both were fixed and tested at the server. Decisions:

- **Accepted as taken:**
  - budgets are bounded at 1–60000 ms. That bounds what can be declared, not a
    judging threshold;
  - the request timeout is 2 × budget + 500 ms, cut to what the run has left;
  - the budget's subject fixes method and path, and inputs that disagree send
    nothing;
  - a duplicate budget in one file is refused;
  - `not_samples` counts the requests that were not samples;
  - the demo's `GET /ready` is declared by an invariant;
  - the fault library times the probe from the fault's own vantage.
- **Plan corrections (accepted):**
  - fields 4 and 12 no longer name `OPTIONS`;
  - field 10's "10 to 50" is now a fixed 20 or 50;
  - criterion 3's cap holds per run and per process. Two processes at once can
    interleave, and LIMITS says so.
- **Both budgets on one route are both judged.** Today, when a route declares
  a p50 and a p95, only the p95 is measured. The p50 is declared, never judged,
  and never reported as unjudged: a check that looks like a gate and isn't.
  One run of 50 samples judges both. Part 2 does this.
- **Every request passes one method check.** `TimeGet` builds its own request
  outside `do()`'s allowlist. It is a constant `GET` today, but the allowlist
  holds only if no request can be built around it. Part 2 routes it through.
- **A budget is written as a plain decimal integer, or it is refused.** The
  two YAML readers disagree on forms like `1e3`, `0o454` and `0454`: YAML 1.2
  and YAML 1.1 read them as different numbers, or as strings. Two readers of one
  INTENT value must not read two values. Both refuse every form but plain
  decimal digits, with each form as a shared fixture case. Part 2 does this.
- **`3be789e` was not re-audited.** It holds the fix for a `url` on another
  path and the scan of packages under `testdata`. Part 2's phase-auditor
  re-audits it first.
- **Registration by reflection** escapes the source scan. The served-catalogue
  test holds instead. Accepted.

Part 1 is complete once `main`'s push run on `716205f` is green, `e2e` included.
Part 2's step 0 confirms it.

**Part 2 — the walk sees slow. Brief and criteria, 2026-11-12.**

**Decisions.**
- **Latency is asked only after errors explain nothing.** The walk runs as it
  does today: `component_fails`, bisection, then the boundary hypotheses in
  `localOrder`. Only if that finds no root — the partial diagnosis "the cause is
  inside X or something it cannot observe, such as added latency" — does a
  second pass ask about latency over the same tree. Errors are cheaper and more
  fundamental. A latency probe costs at least 2.5 s and is `metered`, and a
  failing request has no meaningful latency anyway. The agent loop's audience
  fault is found by the first pass, so it takes no latency reading, and
  narration parity has no noisy measurement to compare.
- **The hypothesis is `latency_budget_exceeded` on a component.** It is
  generated for every component reached from the entry that has at least one
  measurable budget, meaning a `GET` budget. It is tested by
  `probe.http.latency` on each of that component's measurable budgets, in
  subject order:
  - **supported** when one fails;
  - **ruled out** when all pass;
  - **unexplored**, with the probe's reason, otherwise.

  A component with no measurable budget is not given the hypothesis. The partial
  diagnosis names it as unbudgeted, so "no budget declared" is said, not
  implied.
- **A pass rules out only that component's own latency.** For errors, a passing
  request at X rules out everything below X, because the request exercised it.
  A budgeted route need not call what is below it; `/ready` calls nothing. So a
  latency pass rules out X alone, and the second pass descends the tree
  depth-first rather than bisecting. The tree is small, and the walk's probe and
  wall-clock limits still bound it.
- **The root is the deepest slow component whose callees keep their budgets.**
  A slow component whose child is also slow is propagation. The fault tree
  records it as an edge, never as the root. A slow component with a child that
  could not be measured (unbudgeted, refused or inconclusive) is a partial
  diagnosis that names the child.
- **Hop or component, from the same reading, with no new request.** Each sample
  keeps its connection setup (part 1's `connect_us`). Part 2 adds the setup of
  a timed-out request, or the fact that its connection never completed. The rule
  judges two derived series against the same budget:
  - setup alone;
  - the server's time, which is total minus setup.

  When setup alone fails and this agent runs inside X's caller, the root is the
  connection `caller → X`. When the server's time alone fails, the root is X.
  When neither does alone, the diagnosis is partial and names both. When this
  agent runs outside every component, slow setup is "reaching X from this
  agent", not a connection of the system, and the diagnosis is partial. A
  timeout after the connection completed counts against X; a timeout before it
  counts against the hop. There is no new threshold: it is the same budget and
  the same rule.
- **A latency probe never outlives the walk.** The walk's remaining wall clock
  is the probe's deadline. A run cut short is `inconclusive` with the samples it
  has, which is the probe's behaviour at its own deadline, and the hypothesis
  is unexplored.
- **Verification is unchanged.** It re-takes every reading, the latency
  readings included, and `model.Judge` decides. After the known fix the
  library's latency fault is `verified`. After a wrong fix it is
  `not_resolved`. A noisy pass after the fix is `inconclusive`. That is honest,
  and it is not to be retried away.
- **Still no credential** (part 1's decision stands). Budgets on authenticated
  routes stay unmeasurable. Revisit this when such a budget is what stands
  between Culprit and its first finding in someone else's project.

**Work order.**
0. Confirm `main`'s push run on `716205f` is green, both `e2e` legs and
   `narration-parity` included. If a job failed on the runners' network, re-run
   it; if a test failed, stop and escalate. Then have the phase-auditor
   re-audit `3be789e` before anything is built on it.
1. Narrow narration parity (carried in from Phase 35). Inside a reading's
   `measured`, time-shaped values are volatile: keys ending `_ms`, `_us` or
   `_seconds`, and the sample arrays. So are minted ids and record timestamps.
   Nothing else is: a reading's `expected`, a budget and a verdict are compared.
2. Part 1's corrections:
   - both budgets judged from one run, with one reading per budget;
   - `TimeGet` routed through the method check;
   - budget literals held to plain decimal integers in both readers, with a
     shared fixture.
3. The probe joins the walk: `probe.http.latency` discriminates
   `latency_budget_exceeded`, and the setup of a timed-out request is recorded.
4. The second pass, the root rule, and hop or component, in `internal/isolate`.
5. The fault library:
   - the latency fault diagnoses with the demo's budget and verifies after its
     known fix;
   - a wrong fix gives `not_resolved`;
   - the same fault with no budgets declared stays `inconclusive`, saying no
     budget is declared.

   `expected.json`, `results.json` and the README's number are regenerated, the
   number still labelled as planted faults.
6. Update the documents: the README tour shows a budget finding a slow hop.
   LIMITS:
   - latency is asked only after errors;
   - one vantage;
   - a pass rules out one component;
   - how hop and component are told apart;
   - what an unbudgeted component leaves unknown.

   PROBES and PERMISSIONS for the probe's role in the walk.

**Acceptance criteria (part 2).**
- On a synthetic chain A → B → C with C slowed, where B's budgeted route calls
  C:
  - the walk roots at `latency_budget_exceeded` on C;
  - A → B and B → C are recorded as propagation, never as the root;
  - no latency reading is taken before the error pass has found nothing;
  - with B fast and C slow, the root is still C, because a pass at B rules out
    nothing below it.
- From the same samples:
  - setup alone over the budget, with the agent in the caller, roots at the
    connection;
  - server time alone over it roots at the component;
  - neither alone is a partial diagnosis naming both;
  - the agent outside every component is partial, naming "reaching X from this
    agent".

  Each case is a unit test with recorded samples, with no network.
- In CI, on Linux, the fault library's latency fault:
  - diagnoses with root `component:inventory-service`, kind
    `latency_budget_exceeded`;
  - verifies `verified` after its known fix, and `not_resolved` after a wrong
    one;
  - without budgets, verifies `inconclusive`, saying no budget is declared.
- A route with both budgets is measured once (50 requests, counted at the
  server) and gives two readings, each validated by the rule.
- A non-`GET` request built anywhere in `internal/probe` is refused at one
  place, shown red by building one around it.
- `1e3`, `0o454`, `0454` and `300_000` as a budget are refused by the Go loader,
  by the Python model and by the API's manifest model, each from the shared
  fixture.
- Narration parity: a budget that differs between the legs is a difference,
  red before the change; differing samples and timings are not.
- A latency probe started near the end of the walk's wall clock stops at the
  walk's deadline, and the hypothesis is unexplored.
- Every pull-request check is green, both `e2e` legs and `narration-parity`
  included. `LLM_PROVIDER=none` changes nothing.

**Do NOT implement in part 2.**
- No credential sent by any probe.
- No second vantage, and no probe dispatched to an agent elsewhere.
- No latency from telemetry, and no baseline as a reference.
- No early stopping inside a probe's run: the count stays fixed.
- No percentile other than p50 and p95.
- No change to how errors are walked.
- Nothing for Phase 37.

**Architecture review of part 2, 2026-11-12 — signed off. Phase 36 is
complete once `main`'s push run is green.** PR #38 was merged as `d785af4`. I
read the checks from GitHub's API. Two pull-request runs passed every job:
43235902449 on `4c7bc6e` and 43238653732 on `a7c6ca3`. Both included the fault
library, both `e2e` legs and `narration-parity`.

The library's latency fault now ends where the plan wanted it to. It roots at
`component:inventory-service` and verifies after its fix. A wrong fix gives
`not_resolved`. Without budgets it stays `inconclusive`, saying none was
judged. Q21, open since Phase 34, is closed.

The README's step 4 was run for real on Malcolm's machine:
- `diagnose` rooted at `api` with a reproduced p95 of at least 402 ms;
- `verify` said `verified` once the sleep came out.

Three audit rounds found real defects, and all are fixed with red cases:
- a `url` that escaped its route (`/ready%3F/../../admin`, userinfo sent as
  Basic auth);
- YAML merge keys getting past the literal rule;
- a `DELETE` that left the binary with the method scan green.

Decisions:

- **Q26 — two structural facts replace the method scan.** A syntactic scan
  holds only against the forms it knows. Three audits in a row found new ones,
  and the third got a `DELETE` out. That is the denylist pattern again. What
  holds instead is this:
  - **Only `http.go` and `timing.go` in `internal/probe` import `net/http`.**
    This is already true. A test holds it as an allowlist, the way
    `TestTheNetworkBoundaryIsAnAllowlist` holds its allowlist, and an import in
    a third file shows it red. No other file in the package can then name a
    client, a transport or a request constructor.
  - **Every client those two files build comes from one constructor**, and
    that constructor installs `methodGuard`. The guard refuses anything but a
    bodiless `GET` as the request leaves, which is shown red. A request whose
    method is changed after construction still leaves through the guard.

  With both facts held, the 26-form scan is retired; it would need a new case
  for every new syntax, and the facts do not. LIMITS keeps "a guard against
  ordinary code, not a proof against deliberate code". Raw bytes on a socket
  that `net.tcp.connect` opened are outside it. This is carried into Phase 37
  part 1.
- **`planned` becomes required (F).** It is a rule input, and a reading without
  it is judged on its samples alone. It becomes required in Go, Python and the
  API, and the probe goes to version 2. Culprit is unpublished, so no reading
  without `planned` exists outside a developer's database. If one arrives it is
  refused, not re-judged where it is stored. Carried into Phase 37 part 1.
- **The two manifest readers must know the same keys.** The run did not add
  `isolation:` to the demo because the API's manifest model does not know it.
  A user who sets `isolation:`, which the Go loader reads, would therefore break
  the API path: the fresh-clone pattern again, and two readers of one file
  disagreeing. The API's model accepts every top-level key the Go loader does,
  held by a shared list both read, starting with `isolation:`. Carried into
  Phase 37 part 1.
- **`4c7bc6e` was not re-audited.** Q26 retires its method-scan cases. Phase
  37 part 1's phase-auditor re-audits its manifest and fixture changes first.
- **The fault-library job now takes about 11 minutes (it took 3.5).** Accepted.
  When it passes 15 minutes, split it into shards. Before that, a test must
  prove that the shards together cover every case in `expected.json` exactly
  once, because a filter that can skip a case looks like a gate and isn't.
- **Accepted as taken:**
  - the second pass runs only when the error pass found no root and nothing
    failing below the entry;
  - the hypothesis's subject is the component, and each budgeted route is asked
    as its own target;
  - the root rule reads everything below the component, not only its callees;
    this is the plan's own criterion, said properly;
  - two slow branches: the first found depth-first is the root, the other is
    listed, and the diagnosis is partial;
  - a database below a slow root makes the diagnosis partial until Phase 37
    gives databases budgets;
  - how unbudgeted components are named;
  - the hop root's ruling-out by the same reading;
  - `same_run_as` in the verify record;
  - verify's "no latency budget was judged";
  - the demo's default wall clock, which the library's two runs of about 45 s
    fit inside.
- **Plan corrections (accepted):** criterion 5 (Q26 above), and the root rule's
  wording.

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

**How Phase 37 is run — decided 2026-11-12.** Where this block and the fields
above differ, this block wins.

**Three parts, three `/next` runs, an architecture review after each.**
- **Part 1 — reading the database safely.** It covers:
  - the carried-in items;
  - the two capabilities;
  - the boundary, with read-only sessions;
  - `pg_stat_statements` in the quickstart;
  - the demo's own database (P8);
  - index facts, live and declared.

  `culprit check` and capture see indexes. Nothing is timed or planned yet.
- **Part 2 — statements and plans.** `query_mean_ms_max`,
  `probe.db.statement_budget` and `probe.db.plan`, with their readings and
  validation. Its criteria are written at part 1's review.
- **Part 3 — the walk.** `statement_budget_exceeded` and `missing_index`, the
  join across the planes (P5), and the library's fault and its verification.
  Its criteria are written at part 2's review.

Phase 36's last check, `main`'s push run on `d785af4`, is part 1's step 0.

**Decisions — where the fields predate the build.**
- **The boundary is structural, three times over.**
  - **One file opens database connections.** Today
    `internal/capture/database.go` is the only non-test file that imports
    `pgx`. The database probes reach the database through it, or through a
    sibling the allowlist names. An allowlist test holds this, and an import in
    another file shows it red.
  - **That file sends only templates.** A template is an unexported type whose
    values are constants in that file. The only function that reaches `pgx`
    takes a template, never a string. Values travel as bind parameters and are
    never spliced into the text.
  - **Every session is read-only and bounded at the server.**
    `default_transaction_read_only = on` and a `statement_timeout` are set as
    connection parameters. Even if the first two layers failed, Postgres itself
    would refuse a write.

  Field 12's test, which sends an arbitrary statement and an `EXPLAIN ANALYZE`
  and expects both refused before they leave, holds the first two layers. A
  third test sends a write through a deliberately weakened path and sees
  Postgres refuse it.
- **Only one non-constant text is ever sent, and it is part 2's.** It is a
  statement read back from `pg_stat_statements`, in the same session, and sent
  inside `EXPLAIN (GENERIC_PLAN, FORMAT JSON)`:
  - it is chosen by `queryid`, never by an input, a tool argument or a reading;
  - it must be a single statement whose text begins with `SELECT` or `WITH`;
  - it goes through the extended protocol, which cannot carry a second
    statement;
  - `EXPLAIN` without `ANALYZE` executes nothing, and the session is read-only.

  Part 1 builds the boundary that statement will pass through.
- **Nothing an agent says reaches SQL.** Under `culprit mcp`, no tool argument
  names a statement, a table, a column or a query id. The database probes take
  their target from the database endpoint declared in `culprit.yaml`, as Q23
  binds addresses, and the classification test covers every new input.
- **`pg_stat_statements` is never reset**, because resetting is a write.
  Timings are deltas between two snapshots taken in one session (P5). Part 1
  confirms whether the quickstart's image preloads the extension (`SHOW
  shared_preload_libraries`, recorded in the report). If it does not, part 1
  turns it on for the quickstart. Creating the extension in the demo's database
  is the demo's own setup, done by its migrations as their owner, never by
  Culprit.
- **The demo's database (P8).**
  - **Where it lives.** It is a separate database in the quickstart's Postgres,
    owned by its own role.
  - **Its schema.** The schema comes from the demo's own Alembic migrations, so
    the migration reader has real migrations to read.
  - **The seeded table.** It is large enough that a sequential scan and an index
    scan differ by more than any budget part 3 will declare. The run report says
    how large, and why.
  - **The route that reads it.** A new list route on inventory-service reads
    from it. The existing routes and the fault library's existing cases do not
    change.
  - **Dependencies.** The demo may add SQLAlchemy and Alembic to its own
    dependencies; the product gains none.
  - **Culprit's own database** is never the demo's.
- **Index facts use the existing `schema:` subject** (`database`, `table`,
  `column`), so there is no new subject kind:
  - CONFIGURED facts come from the live catalogue, in capture;
  - INTENT facts come from the migration reader, which learns `create_index`
    and `drop_index`.

  What P5 needs is whether a column leads an index, because an index on (a, b)
  serves a filter on a but not on b. That is the predicate. Declared against
  live goes through the existing comparator, so an index the migrations declare
  and the database lacks, or the reverse, is a divergence like any other.
- **The recommended database role holds `pg_read_all_stats`, and `SELECT` on
  the tables it must plan.** Postgres plans only what the role could run, so
  that role *can* read rows, whatever Culprit chooses to send. PERMISSIONS says
  so plainly, as it does for Kubernetes Secrets. `db.rows.read` stays separate
  and is implied by nothing.
- **Redaction comes first.** The widened `redact_credentials` lands before any
  statement text is read, in both languages.

**Part 1 — reading the database safely. Brief and criteria, 2026-11-12.**

**Work order.**
0. Confirm `main`'s push run on `d785af4` is green: the fault library, both
   `e2e` legs and `narration-parity`. If a job failed on the runners' network,
   re-run it; if a test failed, stop and escalate. Then have the phase-auditor
   re-audit `4c7bc6e`.
1. The carried-in items:
   - `redact_credentials` widened, in Go and Python, with conformance cases:
     `password=…`, Slack tokens, `user:pass@host`;
   - Q26's two facts, and the method scan retired;
   - `planned` required, with `probe.http.latency` at version 2;
   - the manifest keys shared by the Go loader and the API's model, starting
     with `isolation:`.
2. `db.stats.read` and `db.plan.read`:
   - in the model, in Go and Python (`capability_conformance.json`);
   - in the catalogue;
   - in the agent's configuration parser;
   - in the control plane's allowance;
   - in PERMISSIONS.

   No capability implies another, and a test holds that.
3. The boundary: one file opens connections, it sends only templates, and every
   session is read-only and bounded. Today's capture and database probes move
   behind it with their behaviour unchanged.
4. `pg_stat_statements`: confirm it is loaded in the quickstart, or turn it on
   (owned by the demo).
5. The demo's database: its role, migrations, seeded table and the list route
   that reads it. `demo-services/culprit.yaml` declares it as a database
   component.
6. Index facts: live from capture, declared from the migration reader.
7. The documents:
   - PERMISSIONS: the capabilities, the recommended role, and what its grants
     reveal;
   - LIMITS;
   - the README's `culprit.yaml` reference.

**Acceptance criteria (part 1).**
- Nothing outside the template set reaches the database. An arbitrary
  statement and an `EXPLAIN ANALYZE` are refused before they leave, and a test
  counts what reaches the driver. The allowlist test fails on a `pgx` import in
  a second file.
- In CI, against the real database, a write sent through a deliberately
  weakened path is refused by Postgres as read-only. `statement_timeout` is set
  on every session.
- The two capabilities validate in Go and Python from the shared fixture, and
  an allowance can narrow them. Neither implies `db.rows.read`, and no
  capability implies another.
- On the demo's database, capture yields the seeded table's index facts and the
  migration reader yields the declared ones. In a test database:
  - an index dropped by hand is reported as declared but missing;
  - an index created by hand is reported as live but undeclared.
- `redact_credentials` removes `password=…`, a Slack token and the password of
  `user:pass@host` in Go and Python, from shared cases, each red without the
  change.
- Q26:
  - a third file that imports `net/http` fails the allowlist test;
  - a client built other than by the guarded constructor fails;
  - the guard refuses a non-`GET` and a body as each leaves.

  Each is shown red.
- A latency reading without `planned` is refused by Go, by Python and by the
  API.
- `isolation:` in `culprit.yaml` is accepted by the Go loader and by the API's
  model. A key the Go loader knows and the API's model does not fails a test.
- From a fresh `git clone`, the quickstart starts with the demo's database,
  its migrations applied and its table seeded.
- The fault library's existing cases are unchanged and green. `LLM_PROVIDER=none`
  changes nothing. Every pull-request check is green.

**Do NOT implement in part 1.**
- No statement timing, no plan, and no budget on a statement: that is part 2.
- No walk change: that is part 3.
- No `EXPLAIN` of any kind sent.
- No row read by Culprit.
- No reset of `pg_stat_statements`.
- No index created or dropped by Culprit.
- No change to Culprit's own database for the demo.

**Architecture review of part 1, 2026-11-12 — signed off; part 1 is complete
when the close-out below merges.** PR #39 was merged as `b3ef508`. I read the
checks from GitHub's API: the pull request's runs on `fcd0b0a`
(43263355094) and on `4760e94` (43267638088) passed every job. Phase 36's last
check is met: `main`'s push run 43250669431 on `d785af4` passed every job.

The run built what it was asked to:
- the carried-in items, each shown red first;
- the two capabilities, with no implication between any pair;
- a session Postgres itself makes read-only, shown in CI (`25006`);
- `pg_stat_statements` preloaded and read back in CI;
- the demo's own database, with a million rows seeded in the database and
  migrations the reader understands;
- `leads_index` facts, live and declared, compared by the existing comparator,
  with a dropped and an added index each found.

It was merged while Q27 was open and blocking. Nothing on `main` is worse for
that: every change is additive, and the boundary it found weak is new in this
part.

- **Q27 — package isolation; Q26's premise and this phase's "one file" were
  both wrong.** The architecture session ruled that a file which cannot *name*
  a type cannot *use* it. In Go, visibility is per package, not per file. Any
  file in a package reaches every unexported field and function in it, with no
  import at all. The phase-auditor showed both:
  - a file in `internal/probe` with no imports reached the guard's own
    transport and sent a `DELETE`, which the server received;
  - a file in `internal/capture` took `openSession`'s connection and sent
    `EXPLAIN ANALYZE`. A read-only session does not stop that for a `SELECT`,
    nor `pg_stat_statements_reset()`.

  Every test stayed green. The boundary is therefore a package with one
  non-test file:
  - **the guarded HTTP client** — the request constructor, the method guard,
    the client constructor and the timing;
  - **the database session** — the session, `send`, the templates and the
    reader.

  Each lives in a package of its own. A test holds that each package has one
  non-test file. Another test, using `go/types`, holds that its exported
  surface names no type from `net/http`, `net` or `pgx`, so no caller can
  unwrap a client, a transport or a connection. The network allowlist names
  the two packages, and `internal/probe` and `internal/capture` stop importing
  `net/http` and `pgx`. This ruling approves that allowlist change: it moves
  existing network use into narrower packages and adds no reach.

  `reflect` and `unsafe` still get through; LIMITS keeps "a guard against
  ordinary code, not a proof against deliberate code". This is built in the
  close-out below.
- **The two manifest readers read one schema.** Three times now a split between
  PyYAML (YAML 1.1) and yaml.v3 (YAML 1.2) has surfaced:
  - literal forms;
  - merged sections;
  - this run's leftovers: `why: yes` is a string to Go and a boolean the API
    refuses, a second YAML document, and an unknown top-level key that Go
    ignores and the API refuses.

  One more fixture case each time is the denylist pattern. The API's loader
  resolves scalars as yaml.v3 does, under YAML 1.2's core schema, with no new
  dependency: PyYAML takes custom resolvers. A shared scalar fixture holds both
  readers. A second document is refused by both. An unknown top-level key is
  refused by both, naming it, from the shared key list. A mistyped `budgets:`
  silently ignored would be a check that looks like a gate and isn't. Built in
  the close-out.
- **The demo database's password is generated**, as the quickstart's bootstrap
  generates every other role's, never fixed in the repository. Built in the
  close-out.
- **Accepted as taken:**
  - `leads_index` on the column-level `schema:` subject, true and false;
  - `inventory-db`'s edge is `background`, so the order walk is unchanged. Part
    3 decides how a walk from the products route reaches the database without
    changing every other walk;
  - 1,000,000 rows in 200 categories, for the reasons the report gives;
  - the preload list set explicitly. It replaces the image's default, which was
    never observed, and LIMITS says so.
- **A plan correction (accepted).** `pg_stat_statements` is not a trusted
  extension, so only a superuser can create it. The demo's setup creates it as
  the server's superuser; its migrations cannot. That is the demo's own setup,
  not Culprit's.
- **The recommended role** holds no `EXECUTE` on `pg_stat_statements_reset`,
  which is the default. PERMISSIONS says so, and says why.
- **`25db425` was not re-audited.** The close-out's phase-auditor re-audits it
  first.

**Close-out of part 1 — brief and criteria, 2026-11-12.** Branch
`phase-37-closeout`, cut from `origin/main` = `b3ef508`. Its first commit is
this sign-off, already in the working tree (message
`../phase-37-1-signoff.txt`). Open a draft pull request and mark it ready when
the run report is committed. Do not stage `shared/uv.lock`.

**Work order.**
0. Confirm `main`'s push run on `b3ef508` is green. Then have the
   phase-auditor re-audit `25db425`.
1. Q27: the two packages, each with one non-test file and an exported surface
   that names no `net/http`, `net` or `pgx` type. The allowlist names them, and
   `internal/probe` and `internal/capture` no longer import `net/http` or
   `pgx`. Behaviour is unchanged.
2. One schema for both manifest readers:
   - YAML 1.2 core-schema scalars in the API's loader;
   - a shared scalar fixture;
   - a second document refused by both;
   - an unknown top-level key refused by both, naming it.
3. The demo database's password, generated by the bootstrap.
4. LIMITS and PERMISSIONS: what each layer of the boundary holds — the package,
   the templates, the read-only session and the role — and what each does not.

**Acceptance criteria (close-out).**
- The phase-auditor's two attacks — a file reaching the guard's transport, and
  a file sending `EXPLAIN ANALYZE` through the session — no longer type-check.
  A `go/types` test holds this, in the way the Q25 registration test does: it
  plants each file and expects the error.
- Each package has one non-test file, and a second file is shown red. Its
  exported surface names no `net/http`, `net` or `pgx` type, and adding one is
  shown red.
- The network allowlist names the two packages. `internal/probe` and
  `internal/capture` import neither `net/http` nor `pgx`. Every existing test of
  the probes, capture and the boundary is unchanged and green.
- From the shared fixture, both readers give the same value, or both refuse,
  for each of these:
  - `yes`, `no`, `on`, `off`;
  - a date;
  - `0454`, `0o454`, `1e3`;
  - `~`;
  - a second document;
  - an unknown top-level key.

  Each case is red on the old API loader.
- No fixed password for the demo's database role remains in the repository, and
  a fresh clone's quickstart still seeds the database.
- Every pull-request check is green.

**Do NOT implement in the close-out.** No statement timing, plan or budget. No
walk change. Nothing outside the boundary, the readers and the demo's password.

**Part 2 — statements and plans. Brief and criteria, 2026-11-12.** This starts
after the close-out merges. Its step 0 confirms `main`'s push run on that
merge.

**Decisions.**
- **`query_mean_ms_max` sits on a database or on one of its tables.** A table
  budget is on `schema:<database>/<table>`; a database budget is on the
  database component. A statement is judged by the strictest budget of the
  tables its plan reads, otherwise by its database's budget. Without
  `db.plan.read`, only a database budget can be applied: a table budget stays
  unjudged, and the reading says so.
- **`probe.db.statement_budget` measures over a fixed window.** It takes two
  snapshots of `pg_stat_statements` 30 seconds apart in one session. The window
  is not configurable, and the walk's deadline cuts it. For each statement in
  the database:
  - the deltas of `calls` and of total execution time are taken;
  - the time is converted once, at reading, to integer microseconds;
  - Culprit's own role's statements are excluded.

  The rule is integer comparison:
  - over budget when `total_us > budget_us × calls`;
  - within budget otherwise;
  - `inconclusive` when no call fell in the window, or when
    `pg_stat_statements_info` shows a reset or an eviction during it.

  There is no interval. `pg_stat_statements` keeps no per-call samples, and its
  cumulative spread cannot be windowed exactly, so a band would be a number
  Culprit chose. The reading shows the number of calls, and LIMITS says that a
  mean of few calls is a mean of few calls. The reading keeps at most 20
  statements, ranked by window time, with a count of the rest. Their text is
  the normalised text, passed through `redact_credentials`.
- **`probe.db.plan`** sends `EXPLAIN (GENERIC_PLAN, FORMAT JSON)` on one
  statement. The statement is chosen by the `queryid` the walk, or the
  statement probe, already read in the same session, and its text comes from
  `pg_stat_statements`, never from an input. The text must begin with `SELECT`
  or `WITH`; anything else, including a leading comment, is refused and the
  probe is `inconclusive`. It is sent through a value only the database package
  can construct from a statistics row, through the extended protocol.

  The plan reading keeps node types, relations, the indexes used, estimated
  rows and costs. Its filter columns are found by matching the relation's own
  column names, from the catalogue, in the filter. The filter expression and any
  constant are never stored.

  The probe has no expectation. It follows the existing convention for a probe
  with an empty `expected_from`. It is evidence for part 3's join, not a
  finding on its own, because a sequential scan of a small table is normal.
  Servers before PostgreSQL 16 are `inconclusive`, saying why.
- **Under `culprit mcp`:**
  - `probe.db.statement_budget` targets the declared database and takes no
    address input;
  - `probe.db.plan` takes a `queryid` that only the walk supplies, so
    `culprit_probe` refuses it. An agent chooses no statement.
- **The readings validate in Go, Python and the API.** The statement verdict is
  re-judged from its integers, as latency readings are.

**Work order.**
0. Confirm `main`'s push run on the close-out's merge is green.
1. `query_mean_ms_max` in both manifest readers and the API's model, from the
   shared fixtures.
2. The two templates for snapshots and the planned-statement value, inside the
   database package.
3. The two probes and their rule, in Go and Python, with a shared fixture.
4. Reading validation in Go, Python and the API.
5. The demo declares a `query_mean_ms_max` on `schema:inventory/products`. Its
   `why` says what it guards.
6. PROBES, PERMISSIONS (what each template reads) and LIMITS.

**Acceptance criteria (part 2).**
- Nothing outside the template set reaches the database: an arbitrary
  statement, `EXPLAIN ANALYZE`, `pg_stat_statements_reset()` and a second
  statement appended to a planned one are each counted and refused.
- The statement rule's shared fixture holds in Go and Python. It includes:
  - over budget;
  - within budget;
  - no calls (`inconclusive`);
  - a reset during the window (`inconclusive`);
  - the integer boundary.

  It is shown red by moving the comparison.
- In CI, on the demo's database with test traffic on the products route:
  - the window finds the category statement over a budget the seed makes it
    exceed;
  - the plan shows a sequential scan of `products` filtering `category`;
  - with an index created on `category` in a test database, the plan shows an
    index scan and the window is within budget.
- A statement holding a secret-looking constant leaves no trace of it in any
  reading: not in the text, not in the plan, not in a filter.
- Without `db.plan.read`, the plan probe is refused and a table budget is
  unjudged, saying so. Without `pg_stat_statements`, both probes are
  `inconclusive`, saying so. Before PostgreSQL 16, the plan probe is
  `inconclusive`, saying so.
- Under `culprit mcp`, `culprit_probe` refuses `probe.db.plan` and any address
  for the statement probe, before anything is sent (counted).
- A statement reading whose verdict disagrees with its integers is refused by
  Go, by Python and by the API.
- Every pull-request check is green.

**Do NOT implement in part 2.**
- No walk change, and no `statement_budget_exceeded` or `missing_index`
  hypothesis: that is part 3.
- No fault-library case.
- No traffic generated by Culprit.
- No reset.
- No `EXPLAIN ANALYZE`.
- No row read.
- No index created by Culprit.

**Architecture review of the close-out, 2026-11-12 — signed off; Q28 and Q29
ruled. Part 1 is complete.** PR #40 was merged as `ee3e19e`. I read the checks
from GitHub's API: the pull request's runs on `21651a8` (43287075789) and
`24cf2a7` (43290346292) passed every job, and no code-scanning alert is open.
Part 1's step 0 is met: `main`'s push run 43272962537 on `b3ef508` passed.

Checked on disk:
- `guardedhttp` and `dbsession` each hold one non-test file;
- no other file under `internal/probe` or `internal/capture` imports
  `net/http` or `pgx`.

The phase-auditor's two attacks now fail to type-check, with the compiler's
own words: "cannot refer to unexported field". CodeQL flagged the first YAML
loader for unsafe deserialisation, and the run answered by changing the design
rather than dismissing the alert. The API now builds plain data from a closed
set of tags and constructs nothing through PyYAML.

The pull request was merged while Q28 was open and blocking. Again, nothing on
`main` is worse for it.

- **Q28 — strict typing in both readers, and agreement held by a generated
  corpus, not by listed cases.** The run is right that a fixture of named cases
  is the denylist pattern again: the auditor's 85 generated manifests found 23
  splits the 16 listed cases did not. The fix has three parts:
  - **One type per field.** Every manifest field has one type. A scalar is
    accepted only when its resolved YAML 1.2 core tag is that type:
    - `why: true` and `name: 0454` are refused by both readers;
    - `max_probes: 1.5` and `max_probes: "5"` are refused by both;
    - `enabled: 1` is refused by both.
  - **Null and empty are refused.** `~`, an empty value and an empty file are
    refused by both, naming the field. Absent is how "not set" is written.
  - **Untyped values keep their text.** A value with no fixed type, such as an
    invariant's `value:`, keeps its text in both readers for anything that is
    not a core integer, float, boolean or null. A date is its text, as written.

  The gate is a differential test in CI. It generates manifests across every
  field and every YAML 1.2 scalar form, plus the structural variants (merges,
  anchors, a second document, an unknown key). Both readers must produce equal
  canonical JSON, or both must refuse. The auditor's harness becomes this test,
  and loosening either reader shows it red. Built as part 2's first item,
  before part 2 adds `query_mean_ms_max` to both readers.
- **Q29 (1) — criterion 6 reworded (accepted).** A case on which the readers
  split at `b3ef508` is red on the reader that split. Cases that never split are
  pins.
- **Q29 (2) — statement text is kept only where Postgres normalises it.** The
  re-audit found SQL `PASSWORD` redaction missing `E'…'`, `U&'…'`, dollar
  quotes and a comment before the quote. A pattern per quoting form is a
  denylist that will lose. The exposure it guards comes from one place:
  `pg_stat_statements` stores a utility statement's text as it was written. A
  `CREATE ROLE … PASSWORD '…'` is therefore readable by any `pg_read_all_stats`
  role, Culprit's migrations' own included.

  Part 2 keeps a statement's text only when the text begins with `SELECT`,
  `WITH`, `INSERT`, `UPDATE`, `DELETE` or `MERGE`. Postgres replaces those
  statements' constants with `$n`. Any other statement, including one whose
  text begins with a comment, is listed by `queryid` and timings, and the
  reading says "text not kept: not a statement Postgres normalises".
  `redact_credentials` stays as the second layer, and LIMITS lists its known
  gaps.
- **Q29 (3) — the statistics template reads only this database.** It filters
  `pg_stat_statements` to the connected database's `dbid` and excludes
  Culprit's own role. PERMISSIONS already says what `pg_read_all_stats` could
  reveal beyond that.
- **Accepted as taken:**
  - the Go loader refuses unknown top-level keys, so an older binary stops and
    names a newer key; the shared list replaces the old tolerance;
  - the alert answered by design;
  - `setup_db` sets the role's password on every run, and is held to
    `inventory`;
  - `boundarytest` is a test-only package.
- **Left, in LIMITS (accepted):** an exported function that returns the
  connection as `any` escapes the surface test. The one-file rule and review
  hold it.

**Added to part 2, 2026-11-12, at the close-out's review.**
- **Step 0:** confirm `main`'s push run on `ee3e19e` is green.
- **Item 1, before anything else (Q28):** strict typing in both manifest
  readers, with null and empty refused and untyped values keeping their text.
  The differential corpus runs in CI, and loosening either reader shows it red.
  `query_mean_ms_max` is then added to both readers under the same rule.
- **In item 2 (Q29):** the statistics template filters to the current
  database's `dbid`, and excludes Culprit's role. Statement text is kept only
  for `SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE` and `MERGE` texts.
- **Added criteria:**
  - The differential corpus agrees on every generated manifest: equal JSON, or
    both readers refuse.
  - Each of the auditor's 23 splits is in the corpus.
  - Loosening either reader turns the corpus red.
  - In CI on the quickstart's database, Culprit's migrations' `CREATE ROLE …
    PASSWORD` appears in no reading, neither as text nor as a fragment, while
    the products statement's text is kept.
  - A statement from another database is not read.

**Architecture review of part 2, 2026-11-13 — signed off; Q31 and Q32
ruled.** PR #41 was merged as `1b2496b`. I read the checks from GitHub's API.
The pull request's runs on `74ab042` (43380877940, attempt 2) and `89152a8`
(43390113268) passed every job, and no code-scanning alert is open. The first
attempt on `74ab042` lost its runner before `e2e (none)` started; the fault
was the runner's, not the change's. Part 1's step 0 is met: `main`'s push run
43293248631 on `ee3e19e` passed.

It was merged while Q31 was open. Q31 blocked only Q30's change, so that is
safe.

**Rulings made in chat during the run, recorded here (2026-11-13):**
- **The generic plan comes from a prepared statement.** The brief's
  `EXPLAIN (GENERIC_PLAN)` cannot work over the extended protocol: every `$n`
  must be bound, and Postgres folds the bound values into the plan, so it
  planned for NULL. The architecture session's spec was wrong. The run instead
  parses the statement as a prepared statement and explains it under
  `plan_cache_mode = force_generic_plan`, on the extended protocol, with
  nothing executed. `TestTheGenericPlanAgainstARealPostgres` holds this in
  CI:
  - the session stays read-only before, between and after every message;
  - `ANALYZE` is never sent, shown red;
  - a second statement appended to the text is refused at parse (`42601`).
- **The demo's plan walks `ix_products_sku` and filters `category`.** It is
  not a sequential scan, because of `ORDER BY sku LIMIT`. The test asserts the
  filter on `category`.
- **An index on `(category, sku)` brings the statement within budget; one on
  `category` alone does not.** On Linux the means per call were:
  - no index: 96.1 ms;
  - `category` alone: 96.4 ms;
  - `(category, sku)`: 0.014 ms.

  Part 3 builds on this.

**Decisions:**
- **Q31 — a probe declares the verdicts it can give.** Q30's ruling keyed the
  exemption on an empty `expected_from`. It would have caught
  `probe.edge.impedance`, which has no expectation plane and does fail, at 3σ.
  The architecture session's rule was wrong again. Keying it on whether a fail
  fixture exists would let a forgotten fixture pass as "cannot fail". The
  structural answer is a declaration:
  - **Every probe's manifest lists the verdicts it can return**, in Go, in
    Python and in the catalogue mirror. `probe.db.plan` lists `pass`,
    `inconclusive` and `refused`; impedance lists all four.
  - **A reading whose verdict its probe did not declare is refused** by
    validation in Go, Python and the API.
  - **The fixture gate requires one fixture for each declared verdict.**
  - **No probe is named anywhere.**

  The exemption by name is removed. Built as part 3's first item.
- **Q32 — statement text is kept only on PostgreSQL 16 and later.** On 14 and
  15, a `SELECT … INTO` is a utility statement whose constants Postgres did not
  normalise, yet its text begins with `SELECT`. The plan probe already needs 16,
  so before 16 the statement probe lists statements by `queryid` and timings,
  with their text withheld, and says so. On 16, CI runs a `SELECT … INTO` with a
  secret-looking constant inside the window and finds no trace of it in any
  reading. If 16 keeps it, the run stops and escalates; it adds no pattern.
  Built in part 3.
- **A2 — the auditor's 23 splits are labelled.** Each split carries its origin
  in the corpus, and the test checks each by label, not by a count. Built in
  part 3.
- **A4 — reworded (accepted).** The `CREATE ROLE … PASSWORD` statements run
  inside the window, written as Culprit's migrations write them, in the demo's
  database and in a Postgres 16 test database. Reproducing the quickstart's own
  Alembic path is not required.
- **The statistics session is bounded by the caller's deadline:** the walk's
  remaining clock, or `--timeout`, as the latency probe is. A window cut short
  is `inconclusive`. Built in part 3.
- **Accepted as taken:**
  - statements a budget applies to are kept before the rest;
  - an exact-integer `queryid` is accepted at the terminal, and a float is
    refused;
  - a statement too large to judge is named in the reason;
  - tables outside `public` are taken as `public`, with a LIMITS entry. This is
    revisited when a schema other than `public` matters.

Part 2 is complete once `main`'s push run on `1b2496b` is green. Part 3's
step 0 confirms it.

**Part 3 — the database in the walk. Brief and criteria, 2026-11-13.**

**Decisions.**
- **The database pass runs third, and from the entry.** It runs only when the
  error pass and the latency pass found no root strictly below the entry. It
  asks about the databases the entry component connects to, by an edge of any
  kind, because a symptom at X with nothing failing or slow below X leaves X's
  own work, and the databases X reads, as what remains. A database that only a
  deeper component reaches through a `background` edge is not asked; LIMITS
  says so.

  Every existing fault-library walk is therefore unchanged. Their roots are
  found by the first two passes, and the latency fault's root, inventory, is a
  callee, not the entry. `inventory-service → inventory-db` stays `background`
  for the order walks.
- **Two hypotheses.**
  - **`statement_budget_exceeded`** is on the budget's own subject: a table
    (`schema:<db>/<table>`) or the database component. It is supported when the
    statement probe's reading fails. A slow entry above it is propagation.
  - **`missing_index`** is on the filtered column's `schema:` subject. It is
    supported only when P5's four planes agree:
    - **OBSERVED:** a statement is over its budget;
    - **the plan:** it filters column C of table T with no index condition
      serving C, whatever the scan node. Ruling 2 showed it need not be a
      sequential scan;
    - **CONFIGURED:** no live index leads C (`leads_index` false);
    - **INTENT:** the migrations declare none.

    The root cites all four.
- **An index exists but the plan does not use it.** That is the `category`-only
  case: a live index leads C, but the plan walks another index for the order
  and filters C. Then the root is `statement_budget_exceeded`, not
  `missing_index`. Its evidence is the plan and the live index, and the
  statement says what the plan does.
- **The recommended change is derived from the plan, deterministically.** It
  is an index whose leading columns are the filtered columns, followed by the
  columns of the index the plan walks for its order, if it walks one. For the
  demo that gives `(category, sku)`. Verification, not the recommendation,
  decides whether a change worked.
- **Without `db.plan.read`:** a database budget can still support
  `statement_budget_exceeded`, but there is no `missing_index`. The diagnosis
  is partial and names the capability. A table budget is unjudged.
- **The walk sends no statement and no request to make traffic.** The statement
  window measures the system's own traffic. In the fault library the load
  generator supplies it, on `GET /products`.
- **The fault library gains the demo's database, and one database fault.**
  - **The healthy head.** The demo's migrations gain `0003`, which adds
    `(category, sku)`, so the quickstart and the healthy stack are within
    budget.
  - **Planting the fault.** The library runs the stack at `0002`, with no index
    on `category`. That is the harness's own setup; Culprit creates and drops
    nothing.
  - **The known fix** is upgrading to `0003`, recorded as a `commit` change
    naming the revision.
  - **The wrong fix** is an index on `category` alone, applied by the harness
    from the library's own test data, and it gives `not_resolved`.
  - **The symptom** is reported on `http:inventory-service/GET /products`.
  - **A latency budget.** The demo declares a p95 budget on `GET /products`,
    set well clear of both the healthy time and the fault's time. The report
    says how it was chosen.
- **The fault-library job:** if it passes 15 minutes, shard it in this part.
  First, a test must prove the shards cover every case in `expected.json`
  exactly once.

**Work order.**
0. Confirm `main`'s push run on `1b2496b` is green.
1. Carried in:
   - Q31: probes declare their verdicts, and readings are validated against
     them;
   - Q32: text kept on 16 and later only, with the `SELECT … INTO` check on 16;
   - A2: the 23 splits labelled;
   - the statistics session bounded by the caller's deadline.
2. The database pass, the two hypotheses, and the join, in `internal/isolate`,
   tested on recorded readings first.
3. The recommended change, derived from the plan.
4. The demo's `0003` migration, the latency budget on `GET /products`, the
   load generator's traffic on it, and the database in the faults stack.
5. The library's database fault, its known fix and its wrong fix. Then
   `expected.json`, `results.json` and the README's number, still labelled as
   planted faults.
6. The documents:
   - the README tour: a database finding;
   - PROBES and PERMISSIONS;
   - LIMITS: the entry rule, the four planes, the unused-index case, what a
     `background` database leaves unasked, and that the system's own traffic is
     the measurement.

**Acceptance criteria (part 3).**
- On recorded readings, with no network:
  - the four planes give `missing_index` on `category`, citing each;
  - a live index on `category` that the plan does not use gives
    `statement_budget_exceeded`, with the plan and the index cited;
  - with no plan, the diagnosis is partial and names `db.plan.read`;
  - with no budget, the database is named unbudgeted.
- No database is asked when the error or latency pass found a root below the
  entry. Every existing fault-library case is unchanged: `expected.json`
  differs only by the new cases.
- In CI, on Linux, the library's database fault:
  - diagnoses `missing_index` on `category`, complete, recommending
    `(category, sku)`;
  - verifies `verified` after `0003` as a `commit` change;
  - is `not_resolved` after the `category`-only index.
- Q31:
  - a reading with a verdict its probe did not declare is refused by Go, by
    Python and by the API, each shown red;
  - the fixture gate requires one fixture per declared verdict, and no probe
    is named anywhere.
- Q32: before 16, no statement text is kept. On 16, a `SELECT … INTO` with a
  secret-looking constant leaves no trace in any reading.
- A2: each of the 23 labelled splits is checked by its label.
- A statement window started near the walk's deadline stops at it, and the
  hypothesis is unexplored.
- Every pull-request check is green. The fault-library job takes 15 minutes or
  less, or is sharded with its coverage proof. `LLM_PROVIDER=none` changes
  nothing.

**Do NOT implement in part 3.**
- No index created or dropped by Culprit. The harness plants the fault and
  applies the fixes.
- No traffic generated by the walk.
- No `EXPLAIN ANALYZE`, no reset, and no row read.
- No route-level dependency declarations in `culprit.yaml`.
- No N+1 (that is Phase 39).
- Nothing for Phase 38.

**Architecture review of part 3, items 1–3, 2026-11-13 — merged as `1d20322`
(PR #42); part 3 continues. Q33 ruled; Q34 raised and ruled.**

PR #42 was merged with Q33 open, the fourth merge past an open question. It
was safe for the same reason as the others: the work is additive.
`cli/testdata/faultlib/expected.json` and `results.json` are byte-identical
to `1b2496b`, and the database pass runs only when nothing was found below the
entry.

**What was verified, and how.** The link to Malcolm's computer was down, and
GitHub's API is not reachable from the architecture session's workspace, so
this review did not read the pull request's check runs. Malcolm reports PR #42
green. The run report records run 43439643068 green on `ffd7bf1`. On the merge
commit `1d20322`, in the workspace, this review ran:

- ruff, pyright, `lint-imports` and the `scripts/check_*` gates;
- the Python unit tests (api with `shared/`, worker, mcp_server, both
  extractors);
- gofmt, `go vet ./...` and `go test ./...` with Go 1.27;
- the CI step's five `dbsession` Postgres tests, on PostgreSQL 16 and on a
  PostgreSQL 15.10 built from source, and `cmd/culprit`'s index and
  demo-database tests.

All are green. The fault library, the Python tests that start Postgres, and the
compose, kind, migration round-trip and image builds need registry images and
did not run here. So step 0 of the next run reads, by id, `main`'s push run on
`1d20322` and PR #42's last run.

**The CI repair (`ffd7bf1`) is accepted.** The cause is right: the official
image's first-boot server answers on the socket, then restarts. The fix is
right too: all four helpers now wait for `pg_isready -h 127.0.0.1`, rather than
retrying.

**Item 1 was never reported.** The run that built it stopped on the red CI
before it wrote §5. Checked here instead:

- **Q31.**
  - With Go's `ValidateFor` made to accept any verdict, two tests go red:
    `TestReadingsAreHeldToTheirProbesDeclaredVerdicts` and
    `TestAnUndeclaredVerdictNeverLeavesTheRunner`.
  - With Python's `validate_for` made to accept any verdict,
    `test_readings_are_held_to_their_probes_declared_verdicts` goes red.
  - The API's refusal is a Postgres-backed test, so it is checked in CI only.
  - The fixture gate names no probe. The exemption keyed on a name is gone.
- **Q32.** `TestNoTextIsKeptBeforePostgres16` is green on 15.10. On 16, a
  statement whose server-side description has no fields is refused before
  planning (`ErrNotAQuery`). The server decides that, not a pattern over the
  text, which is the right shape.
- **A2.** The splits are checked by label
  (`TestTheAuditorsSplitsAreReadAsRecorded`). There are 25 labels, but the
  brief said 23. The next report says which two were added, and why.
- **The deadline.** `TestAWindowCutShortIsUnavailable` is green.

**Item 2 is accepted, and its finding matters.** The isolate tests gave
`probe.db.plan` a hand-built manifest that discriminated `missing_index`. The
real manifest declared nothing, and placement had no case for either kind, so
the binary would never have run the pass. That is pattern 1 and pattern 8 in
one. The fix has the right shape: a test over the real catalogue and placement,
shown red without the declaration.

**Item 3 is accepted.** The recommendation is derived from the plan. The demo's
plan gives `public.products (category, sku)`.

**Q33 — ruled: (a), with three corrections.** INTENT is the migrations' own,
read by the reader that exists, through the plugin path `diagnose` already
has. (b) is rejected: it would be a second reader of the same files in a second
language (pattern 9). (c) is rejected too: it is a person's assertion standing
in for the migrations', and it is wrong the moment `0003` lands.

1. **Static and scoped.** The demo's `culprit.yaml` gains an `extract:`
   section for `inventory-service` only. It runs the Python extractor with
   `--no-import` and `want: [db_schema]`. With `--no-import`, nothing of the
   demo's is imported, so `import shared` cannot break it. Rewrite the
   manifest's comment that explains why it had no `extract:` section, to say
   why this one is safe. The migration chain is read with `ast` either way.

   Checked on `1d20322`: `culprit intent` with such a section gives
   `leads_index` false on `category`, and true on `id` and `sku`. That is, on
   the wrong subjects; see Q34.
2. **The fault is planted in the tree as well as the database.** The walk reads
   INTENT from source, so the fault must exist in the source the walk reads.
   - **At the fault:** the tree holds `0001`–`0002`, and the database is at
     `0002`.
   - **The known fix:** a commit that adds `0003`, with the database upgraded
     to it.
   - **The wrong fix:** a commit that adds a `category`-only migration, applied.

   With `0003` in the tree and the database at `0002`, INTENT and CONFIGURED
   disagree. That is a migration not applied, a different fault. The pass
   rightly leaves `missing_index` unexplored there. It is not this case, and
   it is not built here; LIMITS says so.
3. **One code path in the library.** The library's walks run the demo
   manifest's extractors for every case, so `--no-plugins` leaves the library.
   - The harness makes the extractor runnable in the walk's container. How is
     the harness's choice, stated in the report.
   - The walk reads the committed `extract:` section, changed only where the
     container forces it. The report names any such difference.
   - For the existing cases, `expected.json` is unchanged. `results.json`
     changes for them only in fields the report lists, each explained.

The agent still skips plugins on a production host. A missing index found under
the agent is therefore partial, for want of migration INTENT, and LIMITS says
so. Carrying INTENT extracted in CI to an agent is named future work; it is not
built.

**Q34 — the schema database name. Raised by this review, and ruled.** Found
while checking (a): `culprit intent` names the demo's columns
`schema:inventory-service-db/public.products.*`. Two readers name a component's
database `<component>-db`: the Python extractor always, and Go's
`DatabaseSpec.DatabaseName` when an environment gives no `name`. But the walk,
the budget (`schema:inventory-db/public.products`) and the graph all say
`inventory-db`. Q33's option (a), as raised, would therefore have joined
nothing, and the walk would have stayed partial.

The same split runs through the repository's manifests. Of the 14 components
there that connect to a database by `sql`, 13 have a graph database that
differs from the default subject name. That includes Culprit's own:
`culprit-api` and `culprit-worker` both connect to `culprit-db`, yet
`culprit.yaml` names the schema `culprit-api-db`. Severity finds a database's
owner by trimming `-db`, a fourth copy of the convention.

Ruling: one rule, in one Go function, derived from the model.

- **The rule:**
  - A component's schema database is the database component it connects to by
    its one `sql` edge.
  - With no such edge, it is `<component>-db`, as today.
  - With two or more, it is `<component>-db`, and LIMITS says the walk cannot
    join that component's schema facts to either database.
- **Environments:** an environment's `database.name`, where given, must equal
  the rule's name. Otherwise the manifest is refused, with both names given.
- **Extractors:** the orchestrator passes the name to each extractor in its
  request. This changes `docs/EXTRACTOR_PROTOCOL.md` and both request models.
  The Python extractor uses the name it is given, and falls back to
  `<component>-db` only when an older orchestrator sends none.
- **Severity:** its owner lookup is the inverse of the same rule, not a suffix
  trim.

This renames schema subjects across fixtures, goldens and Culprit's own
self-check, which is the point. The run lists every subject whose database
changed. Putting `culprit-api`'s and `culprit-worker`'s facts on one database
may surface a divergence in the self-check. If it does, escalate it; do not
suppress it.

**Part 3, continued — brief and criteria, 2026-11-13.** Part 3's decisions
above stand, as amended by Q33 and Q34. Its earlier criteria not yet met carry
forward.

**Work order.**
0. Confirm `main`'s push run on `1d20322` and PR #42's last run, each green,
   by id. Then commit the review: apply `../phase-37-3-review.patch` and
   commit with `../phase-37-3-review.txt`.
1. **Q34: one database name.** This is its own commit, before anything that
   depends on it. It covers the rule and its function, the protocol field,
   the extractor, severity's owner lookup, and environment names held to the
   rule. It renames subjects in the fixtures and goldens, and lists every
   subject renamed.
2. **The demo.** This item adds:
   - `0003` `(category, sku)`;
   - the static, scoped `extract:` section (Q33 (1));
   - the p95 budget on `GET /products`, saying how it was chosen;
   - the load generator's traffic on it;
   - the database in the faults stack.
3. **The library's database fault.**
   - The fault is planted in the tree and the database (Q33 (2)), with the
     known fix and the wrong fix as commits.
   - The library runs the extractors (Q33 (3)).
   - Then come `expected.json`, `results.json` and the README's number, still
     labelled as planted faults.
   - Shard the job if it passes 15 minutes, with the coverage proof first.
4. **The documents:**
   - the README tour: a database finding;
   - PROBES and PERMISSIONS;
   - `EXTRACTOR_PROTOCOL.md`;
   - LIMITS: the entry rule, the four planes, the unused-index case, an
     unapplied migration, what a `background` database leaves unasked, the
     system's own traffic as the measurement, the database rule's two-edge
     case, and the agent without migration INTENT.

**Acceptance criteria (part 3, continued).**
- **Q34:**
  - a test of the rule: no `sql` edge, one, two; an environment name that
    agrees, and one that is refused;
  - `culprit intent` on the demo, from a fresh clone, names
    `schema:inventory-db/public.products.category`;
  - one test holds three things to the same database for the demo: the
    `leads_index` from the migrations, the `leads_index` from the live
    capture, and the budget's subject. It goes red, shown, when the extractor
    ignores the name it is sent;
  - severity finds an owner whose database is not `<owner>-db`;
  - every renamed subject is listed in the report;
  - the self-check is green, or any divergence it surfaces is escalated.
- **Q33:**
  - the demo's `extract:` section is `--no-import` and `want: [db_schema]`,
    for `inventory-service` only;
  - the library's walks run it;
  - existing cases: `expected.json` is unchanged, and any change to their
    `results.json` is listed and explained.
- **In CI, on Linux, the library's database fault:**
  - diagnoses `missing_index` on `category`, complete, citing all four planes
    and recommending `(category, sku)`;
  - is `verified` after the commit that adds `0003`;
  - is `not_resolved` after the `category`-only commit.
- **The healthy stack:** the quickstart at `0003` is within both budgets.
- **A2:** the report says why there are 25 labels where the brief said 23.
- **CI:** every pull-request check is green. The fault-library job takes 15
  minutes or less, or is sharded with its coverage proof. `LLM_PROVIDER=none`
  changes nothing.

**Do NOT implement in part 3, continued.** The earlier list stands, and in
addition:
- no Go reader for Alembic files (Q33 (b));
- no `leads_index` asserted in `culprit.yaml` (Q33 (c));
- no `--intent` flag, and no INTENT carried to an agent;
- no new manifest field for a component's database, since it is derived;
- no walk hypothesis for an unapplied migration.

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
