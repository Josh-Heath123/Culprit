# Handoff — the baton between architecture and execution

This file is the state carrier for Culprit's development. It exists because the
architecture conversation and the implementation session are different places,
and a decision that lives only in a chat transcript is a decision that gets made
twice.

**Protocol.**

- **The architecture session writes** §2 (Decisions), §3 (Open questions) and the
  *Brief* line of the current phase in §4. It never writes run reports.
- **Claude Code writes** §4 status transitions and §5 (Last run). It never
  answers an open question in §3 on its own — it surfaces the question and stops.
- **Both read the whole file first.** It is committed, so `git log docs/HANDOFF.md`
  is the decision history.

**Committing.** Use `git commit -F <message-file>`. The
`-m "$(cat <<'EOF' ...)"` form triggers a permission prompt on command
substitution every single time — that is the permission system working correctly,
not a misconfiguration, and it has blocked three phases in a row.

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) |
| Current phase | **28 — CLI, extractor protocol, intent extraction** |
| Status | Ready to start once Phase 27 is committed and merged. |
| Branch | `phase-27-system-model` (staged, uncommitted). `main` already has 26 and 26.1. |
| Blocking questions | **None.** Q1–Q6 all resolved (§3). |
| Last gate run | 2026-09-09, all green — 681 tests, both audits clean (§5) |

Phase 25 (memory visualisation) is **cancelled**. Do not implement it.

---

## §2. Decisions register

Decisions made and not to be relitigated per session. Architectural decisions
D1–D8 live in `docs/DIAGNOSTIC_PLAN.md` §1 with their alternatives and revisit
triggers; this section records the session-level ones and anything that
supersedes the plan.

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-08 | Evolve the existing repository. No new repo. | Requirements changing is normal; the substrate (role model, CI, ingest, Timescale/pgvector) is real capital. |
| 2026-09-08 | Target user is solo developers and small teams without SRE/DevOps. Not enterprise. | Determines that the CLI wedge outranks the production agent in sequencing. |
| 2026-09-08 | Deterministic core; AI optional. `LLM_PROVIDER=none` must produce complete correct output from every command except prose. | This is the product's defensible property and is enforced as a CI job, not an aspiration. |
| 2026-09-08 | Tier-3 business-logic correctness is out of scope permanently. | No oracle exists. Promising it fails the product's own standard on first contact. The shippable version is the unverifiable-surface report (Phase 29). |
| 2026-09-08 | No `mutate`-effect probe and no `*.write` capability in this entire plan. | Structural boundary, not a config flag. Adding one requires its own plan document. |
| 2026-09-08 | Historical baseline is a statistic over `OBSERVED`, never a fourth plane. | Treating "usual" as a proxy for "correct" is the exact mistake the rewrite exists to fix. |
| 2026-09-09 | `configured_facts.value` is NULL unless `grant_ref` names an explicit per-key grant, enforced by a CHECK constraint. Facts carry `value_shape`. | Resolves Q3. A convention against storing credentials is not a control. Nearly free now (table empty), a migration over live data after Phase 30. |
| 2026-09-09 | Phase 26 acceptance criterion 1 reworded; the 10s key cache stays. | Resolves Q4. The original wording was untrue and making it true would put a DB round trip on the ingest hot path. The defect fixed was that revocation previously worked only by accident. |
| 2026-09-09 | The `value_shape` hole is real. Fix is a closed `ValueShape` type in `culprit_model`, landing in Phase 28, not a wider CHECK constraint. §2.2's claim narrowed immediately to what is actually true. | Resolves Q5. A DB constraint cannot protect a capture bundle that is serialised and never inserted — which is exactly the artefact the guarantee is about. Enforcement belongs in the type. |
| 2026-09-09 | Invariant 10: a new gate is not accepted until a deliberate mutation makes it fail, targeting the mechanism believed to be load-bearing. | Phase 27's mutation of the round-trip gate stayed green — the gate was fine, the belief about *why* it worked was wrong. A passing check is not evidence until shown it can go red. |
| 2026-09-09 | `culprit.yaml` round-trip criterion is semantic equality plus a fixed point, not byte equality. Plus a new criterion that `--export` must not silently destroy a hand-maintained file. | Resolves Q6. Byte equality from the first export tests comment preservation — a human convenience, not a model correctness property. The substitution was an honest correction, not a weakening. |
| 2026-09-09 | Commit with `git commit -F <file>`, never `-m "$(cat <<EOF...)"`. | The heredoc form triggers a permission prompt on command substitution every time — correct behaviour, but it has now blocked three phases running. `-F` matches the allow rule cleanly. |
| 2026-09-09 | Two new standing invariants: migrations round-trip tested against a real DB in CI (8); every check's scanned roots covered by a test (9). | Phase 26.1 shipped a downgrade defect the AST symmetry checker structurally cannot see, and two consecutive phases found violations hiding outside a check's scanned roots. Both gaps are now gates. |
| 2026-09-09 | Go for `cli/` — one static binary, CLI and probe agent. | Resolves Q1. D2's revisit trigger stands: ~6k lines by end of Phase 29, or control-plane logic leaking in, means the boundary is wrong. |
| 2026-09-09 | Product first; phase order unchanged. Phases 29, 30 and 32 each also produce a recorded demo and a short written account. | Resolves Q2. The usable-early ordering is also the better portfolio story; capturing it costs an hour per phase and nothing architecturally. |
| 2026-09-09 | `CLAUDE.md` gets an explicit size budget (8 KB), tracked separately from accuracy. | It grew 32.5 KB → 37.2 KB during Phase 26. Accuracy was the stated criterion and was met; size was never a criterion, which was an ambiguity in the brief, not a failure of execution. |

---

## §3. Open questions

Claude Code must not answer these. It surfaces them and stops.

**Q1 — RESOLVED 2026-09-09: yes, Go.** `docs/DIAGNOSTIC_PLAN.md` D2 stands as
written. `cli/` is a Go module producing one static binary that serves as both
the developer CLI and the deployable probe agent. Keep it small and behind the
versioned JSON contract in D3 — the revisit trigger in D2 still applies: if the
Go surface passes ~6k lines by the end of Phase 29, or starts absorbing logic
that belongs in the control plane, the boundary is wrong.

**Q2 — RESOLVED 2026-09-09: product first, portfolio deliberately.** Phase
ordering is unchanged — 29 and 30 stay ahead of 31 and 32, because a thing a
stranger can install and use in sixty seconds is both the better product and,
in the end, the better story. Additional standing obligation: Phases 29, 30 and
32 each produce a recorded demonstration against a real fault and a short
written account of what the engine established and how. Do it at the end of the
phase, while the detail is fresh. No architectural consequence.

**Q6 — RESOLVED 2026-09-09.** Rewording accepted; it was a correction, not a
weakening. "Apply, export, diff is empty" was never the property that mattered —
byte equality from the first export tests comment preservation, which is a
convenience for humans editing the file, not a correctness property of the model.
Semantic equality plus a fixed point tests exactly what the criterion is for.
Applied to `docs/DIAGNOSTIC_PLAN.md` Phase 27, field 14, together with a new
criterion: `--export` must not silently destroy a hand-maintained file, since
comment loss is real even if it isn't a correctness bug. Keep the LIMITS.md
split you wrote between unavoidable normalisation and design choice.

**Q5 — RESOLVED 2026-09-09.** You were right and the plan was wrong. The CHECK
guards `value`, the column extractors are told not to use; `value_shape`, the
one they are steered toward, was unconstrained. And `culprit_model.Fact` carries
neither field, so Postgres was the only enforcement point — leaving a serialised
capture bundle, the artefact the promise is actually about, unprotected. Fix is
a closed `ValueShape` type in `culprit_model`, scheduled into Phase 28 (fields 4
and 14) rather than bolted on now, because that is where Facts are first
constructed and serialised for real. `docs/DIAGNOSTIC_PLAN.md` §2.2 has been
narrowed to claim only what is true in the meantime. Keep the LIMITS.md wording
you wrote — it was already the accurate one.

**Q3 — RESOLVED 2026-09-09.** Yes, make it structural. `configured_facts`
gains a `grant_ref` column and a CHECK constraint `value IS NULL OR grant_ref IS
NOT NULL`; facts carry `value_shape` instead of `value` by default. Recorded in
`docs/DIAGNOSTIC_PLAN.md` §2.2. See the prerequisite task in §4 — this lands
before Phase 27 work begins, while the table is still empty.

**Q4 — RESOLVED 2026-09-09.** Rewording accepted verbatim and applied to
`docs/DIAGNOSTIC_PLAN.md` Phase 26, field 14. The code is correct; the criterion
was wrong. Good catch — that is precisely the kind of plan defect the audit step
exists to surface.

**Q5 — Should `value_shape` have a closed key vocabulary?** (Raised by the 26.1
invariant audit. Does not block Phase 27; wants deciding before Phase 30 writes
real captures.)
26.1 did exactly what its brief said and the CHECK constraint holds, but the
guarantee is narrower than §2.2's sentence "Config values are structurally
excluded, not conventionally" claims. The constraint protects `value` — the
column the design tells extractors *not* to use. `value_shape`, the column it
steers them *towards*, is free-form JSONB, and
`{"type":"url","sample":"postgresql://u:hunter2@db/orders"}` inserts happily
with no `grant_ref`. Verified by execution, not inferred.

So the credential-in-Postgres failure mode Q3 was raised about is reduced, not
closed. §2.2 already defines shape as type / length class / format class, so the
vocabulary is finite and a CHECK over `jsonb_object_keys` (or a `ValueShape`
model in `shared/culprit_model` with a negative test) would close it. Two things
for the architecture session: whether to do that, and whether §2.2's wording
should be narrowed in the meantime, since as written the plan overstates what
the schema does. Related and cheaper: `grant_ref = ''` currently satisfies the
constraint.

Claude Code did not do either — both are outside 26.1's "nothing else" brief.
`docs/LIMITS.md` and the migration docstring were narrowed to state the real
scope rather than the claimed one.

**Q6 — Should `connections` carry an authored order, and should
acceptance criterion 2 be reworded?** (Raised by the Phase 27 phase audit.
Does not block Phase 28.)

Two related things, both about `culprit.yaml` round-tripping.

*The wording.* Criterion 2 says "apply, export, diff is empty". Two of the
three ways an export differs from a hand-written file are unsatisfiable by
any database-backed round trip, not defects: YAML comments live in the
parser rather than the document, and "did the author write `kind: http`
explicitly or leave it to the default?" is not information the schema
stores — `connections.kind` holds `http` either way. Phase 27 therefore
checked the criterion as *semantic* equality (the exported manifest parses
to a `Manifest` equal to the applied one) plus a fixed point (export is
byte-identical on re-export, and re-applying reports zero writes), and
documented the normalisation in `docs/LIMITS.md`. The phase auditor judged
that an honest satisfaction rather than a weakening, and proposed:

> `culprit.yaml` round-trips: applying a manifest, exporting, and
> re-applying the export produces no writes; the exported manifest parses
> to a `Manifest` equal to the applied one; and export is a fixed point
> (exporting an exported file is byte-identical). The exporter emits a
> canonical form, so a byte diff against a non-canonical hand-written file
> is not expected.

Worth adopting into `docs/DIAGNOSTIC_PLAN.md` so the next auditor can
execute it without a judgement call.

*The choice underneath it.* The third difference — each component's
connections being sorted by `(to, kind)` — is **not** unavoidable.
Component order survives because `apply_manifest` records each
component's file position as its `sort_order`; the identical mechanism
was available for connections and was not used, and `connections` has no
`sort_order` column. Adding one would bring the export nearer the literal
criterion at the cost of a column that exists only for presentation.
Claude Code did not decide this either way; `docs/LIMITS.md` now marks
that bullet explicitly as a design choice rather than a necessity.

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | **complete** | Signed off 2026-09-09. All five acceptance criteria met (criterion 1 as reworded). Verification quality was the bar for every phase after this one. |
| 26.1 | `configured_facts` value safety | **complete, pending commit** | Signed off 2026-09-09. Caught two defects in the brief itself: the CHECK as specified would have inverted its own intent against `value NOT NULL DEFAULT 'null'::jsonb`, and the guarantee was narrower than §2.2 claimed. Both corrected. |
| 27 | The system model (the circuit) | **complete, pending commit** | Signed off 2026-09-09. Found two defects in the plan itself (field 11's networkx contradiction, criterion 2 unsatisfiable) and four real regressions in its own work, including `--export` laundering `declared_by` so a later apply could delete an accepted topology suggestion. Correlation ignoring `connections.kind` correctly deferred — now carried into Phase 32. |
| 28 | CLI, extractor protocol, intent extraction | current | Go confirmed (Q1). Biggest phase so far and the one carrying the polyglot risk, so hold the D3 line hard: parse artefacts, ask the app to introspect itself, and only then thin per-language extraction. Two non-negotiables — the closed `ValueShape` type from the Q5 remediation, and a fixture corpus containing **at least two projects you did not write**, in stacks you do not control. That second one is the only defence against building an extractor that only works because everything in this repo is FastAPI. |
| 29 | The divergence engine | not started | First shippable product. This is the wedge — treat its acceptance criteria as the real bar, especially "zero findings on a fixture known to be correct". |
| 30 | Environment capture and cross-env diff | not started | — |
| 31 | Probes | not started | — |
| 32 | Fault isolation and the Investigation | not started | — |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

**Standing task, not a phase — `CLAUDE.md` size budget.** It is 37.2 KB
(~9.3k tokens loaded every session) and grew during Phase 26. Phase 26's
criterion was accuracy and that was met; size was never stated, which was an
ambiguity in this file's brief. Target **under 8 KB**: keep what the product is
now, the current phase and branch, the scope ceilings, the commands table, the
CRLF warning, and a pointer to `docs/DIAGNOSTIC_PLAN.md`. Move the determinism
and database material out — `.claude/rules/` already carries it and loads only
when the relevant files are touched. Move the phase-by-phase history out — the
three plan documents already hold it and load on demand via `@` imports. Do this
as its own commit, not folded into a phase.

---

## §5. Last run

Claude Code overwrites this section at the end of every `/next`.

```
Phase:        27 — The system model (the circuit)
Branch:       phase-27-system-model (off 8a36e62)
Started:      2026-09-09
Finished:     2026-09-09

Scope note:   /next advanced ONE ledger row. Phase 28 was NOT started.
              Correction to the previous run report: `main` was NOT two
              branches behind. Both 26 and 26.1 were already merged
              (1a3c989, 8a36e62); §1 said otherwise and was stale. No
              merge was needed and none was done.

Gates:        (from /verify; every one re-run independently by phase-auditor)
  lint             PASS   (api+shared+scripts+examples, worker, demo-services, mcp_server)
  typecheck        PASS   (0 errors x4, plus frontend tsc --noEmit 0 errors)
  lint-imports     PASS   (4 contracts kept)
  schema-drift     PASS   (16 worker tables match api's ORM)
  tests            PASS   (api 574 (+6 after the audit), worker 86, mcp_server 21; 3 skipped)
  coupled-files    PASS   (the declared pair both changed)
  no-llm-imports   PASS   (6 deterministic packages)
  migration-sym    PASS   (4 files)
  scan-coverage    PASS   (NEW — 191/191 Python files covered by both repo-wide checks)
  migration-round-trip  PASS   (NEW — upgrade -> seed -> downgrade base -> upgrade)

Acceptance criteria (phase-auditor, executed not inferred):
  1. An existing deployment upgrades with no service/dependency data loss
       MET. api/tests/test_model_migration.py (15 tests) migrates a
       container to a3d81f6c4b27, inserts the real legacy topology
       (3 services, 4 edges, 3 api_keys) as raw SQL, THEN upgrades.
       Names, display names and all four edges survive; zero orphaned
       api_keys; grants verified against information_schema, not read
       out of the migration.
  2. `culprit.yaml` round-trips: apply, export, diff is empty
       MET IN SUBSTANCE, NOT AS LITERALLY WORDED. The auditor ran the
       real CLI: `diff` is NOT empty. Two of the three deviations are
       unsatisfiable by any DB-backed round trip (YAML comments are not
       in the document; "was `kind: http` written or defaulted?" is not
       stored). The auditor's hostile 6-component manifest round-tripped
       with exactly two deltas: `kind: http` dropped, and two same-pair
       edges reordered. Checked instead as semantic equality + fixed
       point + zero-write re-apply. Auditor verdict: "an honest
       satisfaction of the criterion, not a weakening". Rewording
       proposed as Q6.
  3. The dashboard renders components and typed connections
       MET. Rendered in headless Edge against a live API with a real
       admin login. The auditor's screenshot shows a component card with
       `-> orders-cache [cache] background`, `-> orders-db [sql] on
       request path`, `-> stripe [dns] unclassified`, `-> stripe [http]
       on request path`, and a kind selector reading `frontend`.
  4. Given a symptom component, the ordered set of upstream connections
       MET. GET /model/graph?symptom=edge-web returned, in hop order:
       edge-web-[http]->orders-api, orders-api-[sql]->orders-db,
       orders-api-[dns]->stripe, orders-api-[http]->stripe. Background
       edge excluded, `unknown` included, unknown component -> 404 not
       an empty path, unauthenticated -> 401.

Definition of done:
  The four criteria above         MET
  demo-services/ described by a
    committed culprit.yaml        MET. demo-services/culprit.yaml
                                  applied to a fresh DB by the auditor:
                                  3 components + 4 connections, matching
                                  the legacy topology exactly.
  docs/LIMITS.md updated          MET (six new entries)
  CLAUDE.md status current        MET
  docs/HANDOFF.md updated         MET (§1, §3 Q6, §4, §5)
  Committed                       NOT DONE. `git commit` was denied at
                                  the permission prompt — the third time
                                  in a row (26, 26.1, 27). Everything is
                                  staged: `git diff --cached --stat main`
                                  shows 45 files, +5630/-635, and that is
                                  exactly the tree every gate above was
                                  run against. Re-running the commit is
                                  the one step left. Not retried without
                                  approval.
  Merged to main                  NOT DONE, deliberately — the human
                                  review checkpoint.

Field 17 ("do NOT implement yet") — RESPECTED, verified by execution:
  no contract content (contracts table empty, ZERO grants to any role,
  every connection's contract_id null, no /contracts route in the
  generated OpenAPI); no probes; no fault-tree UI (grep across
  frontend/src, api/app, shared: zero matches).

Built:
  - api/migrations/versions/7c2e94b1f0aa_*.py — services RENAMED to
    components (so every FK and GRANT followed it), connections as a new
    table keyed on (from, to, kind), empty contracts table, data
    migration, grants carried across.
  - shared/culprit_model/graph.py — the pure directed model: Component,
    Connection, closed ComponentKind/ConnectionKind/Criticality/
    DeclaredBy, reachability, and upstream_connections() for request-path
    derivation. + shared/tests/test_graph.py (15 tests on a branching
    topology, not the demo triangle).
  - api/app/model/ — manifest.py (culprit.yaml schema, loader, credential
    refusal, canonical dumper), schemas.py, service.py, router.py.
  - api/scripts/apply_model.py (replacing apply_services.py),
    demo-services/culprit.yaml (replacing infra/demo-services.yaml).
  - api/app/registry/ rewritten as a thin /services alias over the model.
  - frontend: useModel.ts, typed-connection editing and a component-kind
    selector in SettingsServices.tsx.
  - scripts/check_migration_round_trip.py (invariant 8) + its own CI job;
    scripts/check_scan_coverage.py (invariant 9) + scripts/tests/
    test_scan_coverage.py + CI step.

Plan corrections — things the brief could not have known:
  1. FIELD 11 IS SELF-CONTRADICTORY. It says "no new dependencies —
     networkx is already present and is retained for directed traversal",
     but networkx is a *worker-only* dependency, and field 4 puts
     graph.py in shared/culprit_model/, which api installs too. Using
     networkx there would have made it a NEW dependency of api — the one
     thing field 11 forbids. graph.py is plain-BFS Python instead. D4
     bounds the model at "hundreds of nodes"; the stdlib covers that
     completely. worker/app/correlation/graph.py keeps its own networkx
     until Phase 32 removes it.
  2. FIELD 10's "culprit.yaml at repo root" does not fit this repo. That
     is the right convention for a *user's* repository, where the root is
     the system being modelled. This repository's root is Culprit itself,
     which is not the system the three demo services make up. The file is
     at demo-services/culprit.yaml, which keeps the actual rule ("the
     manifest sits at the root of the thing it describes") true.
  3. CRITERION 2's literal wording is unsatisfiable. See above and Q6.

Found and fixed en route — each caught by execution, not review:
  - MY OWN MUTATION TEST OF THE NEW ROUND-TRIP GATE PASSED WHEN IT
    SHOULD HAVE FAILED. I removed `ON CONFLICT DO NOTHING` from the
    downgrade expecting the gate to go red; it stayed green. The comment
    I had written was wrong: the GROUP BY is what collapses duplicate
    pairs, and ON CONFLICT was redundant. Removing the GROUP BY *does*
    fail the gate, with the exact duplicate-key error. Comment corrected
    to say what actually holds the line. Worth recording because the
    failure mode here is a plausible-sounding comment that would have
    survived any amount of reading.
  - THE NEW SCAN-COVERAGE GATE IMMEDIATELY FOUND A REAL BLIND SPOT on
    its first run: examples/instrument_python.py was linted by nothing
    and subject-checked by nothing. Now covered by both; it needed one
    lint fix. This is invariant 9 paying for itself within the phase that
    introduced it.
  - I DROPPED mcp-reader's GRANT when replacing service_dependencies
    with connections. beab08d5f92f had granted it SELECT; my migration
    re-granted correlation-engine, api-reader and registry-admin and
    silently shrank mcp-reader. Caught by the mcp_server suite. Fixed,
    and now pinned by a set-equality test over every grant on
    components/connections/contracts, so a *gained* grant fails too —
    the subset assertions I wrote first could only catch a lost one.

From the two audits (invariant audit: CLEAN, 0 violations; phase audit:
all criteria met). Everything below was found as a "risk worth noting"
rather than a violation, and all of it was fixed or documented here
rather than deferred:
  Fixed:
  - PATCH /services/{id} had become non-atomic — a regression I
    introduced. patch_component commits internally, so a PATCH carrying
    both display_name and a typo'd depends_on returned 400 with the
    display name already written. Dependencies are resolved first now,
    matching create_service. Regression test added.
  - `--export` laundered declared_by, defeating the accepted-suggestion
    guarantee. export_manifest emitted edges of every provenance;
    _apply_connections then rewrote them to culprit_yaml, so the
    documented `apply_model --export > culprit.yaml` workflow made
    accepted topology suggestions manifest-owned and therefore deletable
    by a later apply — contradicting accept_topology_suggestion's own
    docstring. Export now omits edges the manifest does not own.
  - The alias's data-loss guard had NO TEST. docs/LIMITS.md promised in
    writing that a legacy depends_on PATCH cannot delete a sql edge, and
    deleting the guard would have kept the whole suite green. Tested now.
  - GET /model/graph returned disabled components as nodes while every
    traversal treated them as absent. Now excluded from the graph
    (GET /model/components still lists them, which is what Settings
    needs).
  - A first apply reported each new component as both created AND
    updated, because sort_order was set in a second pass. Set at
    creation now.
  Documented in docs/LIMITS.md rather than changed:
  - Correlation adjacency ignores connection kind, so declaring a `sql`
    edge makes those two components correlate. Zero impact at upgrade
    (every migrated row is http). Deliberately not fixed: D5 says this
    engine is replaced in Phase 32, not adapted, and teaching it half a
    notion of kind would change correlation behaviour in a phase whose
    first criterion is that nothing is lost.
  - A legacy depends_on PATCH flattens declared_by to culprit_yaml,
    which can make a later apply delete an accepted suggestion.

Surfaced, deliberately NOT done — wants a decision, not a guess:
  - Q6: whether connections should carry an authored order (component
    order is preserved; edge order is not, and that asymmetry is a
    choice, not a necessity), and whether criterion 2 should be reworded
    in docs/DIAGNOSTIC_PLAN.md. Does not block Phase 28.
  - The frontend has no test tooling at all — no vitest, no playwright,
    nothing in package.json. Criterion 3 is met, but nothing in CI
    protects it; the auditor had to install puppeteer-core to verify it.
    Not this phase's brief.

Blocked on:  The commit itself, denied at the permission prompt. Every
             gate is green against exactly the staged tree.
```

## §6. Escalate to the architecture session when

Do not guess on any of these. Stop, write the question into §3, and stop.

- The plan's stated interface, data model or acceptance criterion turns out to be
  wrong or under-specified against the real code.
- Implementing a phase appears to require something on its own field-17 list.
- A gate can only be made green by weakening it — widening a `lint-imports`
  contract, adding a `# type: ignore`, skipping a test, widening a Postgres role.
- A decision in §2 would have to be reversed.
- Two intent sources disagree in a way the plan does not describe how to rank.
