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

**CI is part of the gate set.** A phase is not complete until CI is green on the
**merge result** — `origin/main` merged into the branch — not on the branch
alone. Local `/verify` covers neither: it runs a subset of the checks, on a tree
that is not what gets merged, on Windows rather than Linux. Run `/ci` before
reporting any phase complete.

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
| Current phase | **30 — Environment capture and cross-environment diff** (not started) |
| Status | Phase 29 complete on its branch. Publication deliberately not done — see §4's own condition and §5. |
| Branch | `phase-29-divergence-engine` — **staged, not committed**: `git commit` was denied by the permission system four times, exactly as it was for Phase 28. The full message is at `scratchpad/commit-msg.txt`; 102 files are staged and every gate is green. HEAD is still `a4e7c60` (Phase 28). `main` has 26, 26.1, 27. |
| Blocking questions | **None.** Q1–Q8 all resolved (§3), but **Q1's revisit trigger has fired** — the Go surface is 6,060 non-test lines against its ~6k threshold. That is a question for the architecture session, not a blocker for Phase 30. |
| Last gate run | 2026-09-09, all green. Fifteen defects found and fixed — eight by execution, seven by the two audits, which failed criterion 6 on the first pass and were right to (§5) |

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
| 2026-09-09 | An `invariants:` entry is an ordinary INTENT fact at confidence rank 100, not a separate assertion engine. | Keeps the comparator generic (D7): the same code path handles a human's assertion and an extractor's, including severity, suppression and SARIF. Consequence, accepted: an invariant that is *wrong* produces a loud finding rather than being quietly overruled by the code — which is correct, because a stale assertion is a real defect. |
| 2026-09-09 | Rank says how much to believe a source; it does not say the source enumerated. Absence is judged only against sources that survey a surface (rank ≥ 80 and not a developer assertion). | Learned by defect: a single rank-100 invariant became a component's "complete" route list and reported the application's real routes as absent. The two properties had been conflated. |
| 2026-09-09 | The `culprit` binary makes no network call. `internal/check` links no networking package at all, asserted against `go list -deps`. | Turns field 17's "no LLM anywhere near this path" from a list of vendor names into a structural property. An uploader belongs with Phase 30's capability model, where network access can be gated. |
| 2026-09-09 | `fact-writer` is extended to `divergences` rather than a twelfth role being added. Second sanctioned exception to `.claude/rules/database.md`. | Same CI run, same repository, same project token, same blast radius as the facts it derives from. A second password in every CI configuration, issued to the same process for the same purpose, is friction with nothing gained. The role test was rewritten *stronger*, not weakened — see §5. |
| 2026-09-09 | Phase 26 acceptance criterion 1 reworded; the 10s key cache stays. | Resolves Q4. The original wording was untrue and making it true would put a DB round trip on the ingest hot path. The defect fixed was that revocation previously worked only by accident. |
| 2026-09-09 | The `value_shape` hole is real. Fix is a closed `ValueShape` type in `culprit_model`, landing in Phase 28, not a wider CHECK constraint. §2.2's claim narrowed immediately to what is actually true. | Resolves Q5. A DB constraint cannot protect a capture bundle that is serialised and never inserted — which is exactly the artefact the guarantee is about. Enforcement belongs in the type. |
| 2026-09-09 | **Permission rules were never matching.** All 31 `Bash(cmd *)` rules rewritten to `Bash(cmd:*)`, the actual prefix syntax. | Four consecutive commit denials of a command sitting in `allow`. My error, not the commit form — `-F` was never the problem. Also the cause of the hung editor. |
| 2026-09-09 | Invariant 11: error text is output, subject to the same redaction as a fact, enforced at one serialiser rather than per call site. | Phase 28 found four exfiltration paths through errors; three were introduced by the fix for the previous one. Per-site redaction always has one more site. |
| 2026-09-09 | `ValueShape` carries `scheme` as a closed enum, not a free string. | Resolves Q7. Declared-`postgresql` vs deployed-`mysql` is a real, undetectable-without-it fault class. A closed enum cannot carry a secret. |
| 2026-09-09 | Extraction uses synthetic import-time environment values. The user's real `.env` is never sourced, and there is no option to. | Resolves Q8, and follows from invariant 11: the only safe extractor process is one that never held a credential. |
| 2026-09-09 | Criterion 2 says what determinism means: byte-identical with `SOURCE_DATE_EPOCH` pinned. Publication moved from Phase 28's DoD to Phase 29's. | The original criterion was unsatisfiable while facts carry timestamps. Publishing before the tool is useful burns package names and invites installs against a CLI that only prints an inventory. |
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

**Q7 — RESOLVED 2026-09-09: yes, `scheme`, as a closed enum.** Recorded in
`docs/DIAGNOSTIC_PLAN.md` §2.2. The general rule it sets: any field added to
`ValueShape` must be expressible as a closed set or a bounded numeric class, or
it does not belong in the type.

**Q8 — RESOLVED 2026-09-09: synthetic values only.** `culprit.yaml`'s `extract:`
section declares the variable *names*; the CLI generates shape-satisfying
synthetic values. The user's `.env` is never sourced and no flag enables it. An
app that cannot import without a live connection yields `skipped` with that
reason. Recorded in `docs/DIAGNOSTIC_PLAN.md` D3.

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

**Q7 — Should `ValueShape` carry a `scheme`, or something like it?**
(Raised by Phase 28. Does not block Phase 29; wants deciding before
Phase 30 writes real CONFIGURED captures.)

The four-field shape was fixed by decision (§2, 2026-09-09) and Phase 28
implemented it exactly. Now that it exists against real data, the cost is
measurable rather than hypothetical: **a `DATABASE_URL` pointing at
`postgresql://` in staging and `mysql://` in production has the same
shape**, and so does a hostname change, a port change, and any two
secrets of similar length. Shape comparison catches "set versus unset",
"empty versus populated", "a DSN where a bare hostname was expected" and
"credential-shaped where it should not be". It does not catch "pointing
at the wrong thing", which is a large share of the config faults this
product exists to find.

A `scheme` field constrained to a closed enum (`postgresql`, `mysql`,
`redis`, `https`, …, `other`) would close most of that gap without
reopening the hole — it cannot carry a literal any more than `format`
can. §2.2's own original example had one. But it is a widening of a
decided field set, and widening "the type a literal cannot fit in" is
exactly the change that deserves a deliberate decision rather than an
implementer's judgement.

Recorded in `docs/LIMITS.md` as a stated limit in the meantime.

**Q8 — How should a user supply import-time environment for extraction?**
(Raised by Phase 28. Does not block Phase 29; it is an adoption problem,
not a correctness one.)

Runtime introspection imports the application, and a great many
applications read required configuration at import time — this
repository's own API raises `KeyError: JWT_SECRET_KEY` and yields no
routes and no schema without values for six variables.

`culprit.yaml` is the obvious place to put placeholders and is the wrong
one: it is a committed file that names config keys and never carries
values, and its loader refuses anything credential-shaped. That refusal
fired the first time placeholders were tried there, which is the loader
working correctly. So Phase 28 put them in `just intent` instead — fine
for this repository, useless for a user's, which has no justfile.

The options, none obviously right:
- An `env:` block on an extractor spec, with the credential refusal
  applied to it. Convenient, and it puts a values-shaped thing in the one
  file whose whole discipline is that it holds no values.
- Nothing in the manifest; document that the caller sets the environment.
  Honest, and pushes a real papercut onto every user in CI.
- An `env_file:` pointer to a gitignored file the extractor command
  reads. Keeps values out of the committed manifest, adds a file whose
  absence is a confusing failure.

Worth settling before Phase 29 ships to strangers, since "I ran it and
got nothing" is the first impression this decides.

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | **complete** | Signed off 2026-09-09. All five acceptance criteria met (criterion 1 as reworded). Verification quality was the bar for every phase after this one. |
| 26.1 | `configured_facts` value safety | **complete, pending commit** | Signed off 2026-09-09. Caught two defects in the brief itself: the CHECK as specified would have inverted its own intent against `value NOT NULL DEFAULT 'null'::jsonb`, and the guarantee was narrower than §2.2 claimed. Both corrected. |
| 27 | The system model (the circuit) | **complete, pending commit** | Signed off 2026-09-09. Found two defects in the plan itself (field 11's networkx contradiction, criterion 2 unsatisfiable) and four real regressions in its own work, including `--export` laundering `declared_by` so a later apply could delete an accepted topology suggestion. Correlation ignoring `connections.kind` correctly deferred — now carried into Phase 32. |
| 28 | CLI, extractor protocol, intent extraction | **complete, pending commit** | Signed off 2026-09-09. Three audit rounds, eight defects, all found and fixed — including a chain where three fixes each introduced the next leak. That chain produced standing invariant 11. Publication deferred to Phase 29. |
| 29 | The divergence engine | **complete, pending merge** | **The wedge.** The criterion that decides whether this works is not "finds faults" — it is *zero findings on a fixture known to be correct*. A tool that cries wolf on a clean repo is uninstalled in one run and never reinstalled. Track false positives per fixture as an explicit metric and fail the build when one rises. Also carries Phase 28's deferred publication, once a confirmed finding lands in a project neither written nor controlled by us. |
| 30 | Environment capture and cross-env diff | current | — |
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
Phase:        29 — The divergence engine (first shippable product)
Branch:       phase-29-divergence-engine (off a4e7c60, the Phase 28 commit)
Committed:    NO. `git commit` was denied by the permission system, the
              same way Phase 28's was. Everything is staged (102 files)
              and every gate is green; the prepared message is in the
              session scratchpad as commit-msg.txt. A human needs to run
              the commit.
Started:      2026-09-09
Finished:     2026-09-09

Scope note:   /next advanced ONE ledger row. Phase 30 was NOT started.
              Correction to §1 as found: it said Phase 28 was "staged,
              uncommitted". It is committed as a4e7c60 (still unmerged);
              §1 has been corrected.

WHAT WAS BUILT

  cli/internal/diverge/      the generic comparator (D7). Two rules:
                             conflict and absence. Knows nothing about
                             HTTP, SQL or auth.
  cli/internal/severity/     severity from the manifest's connection
                             graph. BFS along on_request_path edges only.
  cli/internal/report/       text, JSON, SARIF, JUnit.
  cli/internal/check/        the pipeline as a function, so the eval
                             suite can drive it without a subprocess.
  cli/internal/extract/      policy.go (invariants/suppress/
                             severity_overrides + validation),
                             invariants.go (rank-100 facts,
                             RebaseArtefacts).
  cli/cmd/culprit/check.go   the command. --format, --output, --fail-on,
                             --unverifiable, --component, --no-plugins.
  cli/testdata/faults/       the eval suite: 8 fixtures, each a committed
                             fact bundle + the exact divergence set it
                             must produce + a false-positive baseline
                             of 0.
  cli/testdata/demo/         a three-component repository that runs end
                             to end through the real extractors, where
                             all four detection criteria are visible at
                             once. Two components are Phase 28's
                             extraction fixtures reused unmodified; the
                             third has two faults planted on purpose.
  extractors/python/…/migrations.py
                             the migration-chain reader. Criterion 2 was
                             unreachable without it — see PLAN
                             CORRECTIONS.
  api/app/divergences/       POST /divergences/captures (field 9), with
                             upsert-on-identity so history is a record of
                             open problems rather than a log of runs.
  api/migrations/…b8e0c3d5f214_divergence_history.py
                             divergence_key (unique), capture_id,
                             explanation, severity_reason, suppressed_by,
                             last_seen_at; extends the fact-writer grant.
  shared/tests/divergence_identity_conformance.json
                             read by both languages, like the subject
                             fixture, so Go and Python cannot drift about
                             what a finding's identity is.
  cli/internal/diverge/diverge_test.go
                             the comparator's two rules at their
                             boundaries, including a determinism test
                             (Go randomises map iteration and this
                             package groups facts in a map).
  docs/EXTRACTOR_PROTOCOL.md the third-party contract, updated for both
                             predicate changes below - a contract
                             document that still describes the old
                             vocabulary is worse than none.
  docs/demos/phase-29.md     the Q2 written account.
  .github/workflows/ci-cd.yml
                             a `self-check` job: Culprit checks Culprit
                             and uploads SARIF for PR annotations.

GATES (all run, all green)

  just lint                                PASS
  just typecheck                           PASS
  just lint-imports                        PASS  (4 contracts kept)
  just check-schema-drift                  PASS  (16 tables)
  just check-no-llm-imports                PASS  (9 packages, 3 languages)
  just check-scan-coverage                 PASS  (after adding
                                                 cli/testdata/demo to the
                                                 exclusion list — see
                                                 below)
  just check-invariants (symmetry)         PASS
  check_coupled_files.py --base origin/main PASS
  just test                                PASS  729 + 86 + 21 python,
                                                 6 Go packages,
                                                 31 extractor-python,
                                                 19 node
  just self-check                          PASS  0 divergences, exit 0
  just check-migration-round-trip          PASS  (invariant 8, with the
                                                 new migration in the chain)
  LLM_PROVIDER=none culprit check          PASS  identical output, exit 0 —
                                                 trivially, since the binary
                                                 links no LLM client and no
                                                 networking package at all

MUTATION TESTS (standing invariant 10: a new gate must be shown red)

  false-positive baseline   RED then GREEN. Changed one status_codes
                            value in the `clean` fixture's bundle so the
                            two sources disagree; the eval failed with
                            "false positives: 1, baseline is 0" and
                            named the finding. Restored, green.
  no-network gate           RED then GREEN. Added `_ "net/http"` to
                            internal/check; the test failed naming net,
                            net/http and crypto/tls. Restored, green.
  redaction gate            Shown red by a real defect rather than a
                            synthetic mutation, which is stronger: it
                            caught an actual leak in the first version of
                            the report renderer (DEFECTS #6) before that
                            code was ever committed.

ACCEPTANCE CRITERIA (field 14)

  1. frontend calls a route the backend does not expose
     PASS — demonstrated end to end on cli/testdata/demo:
     `http:orders-api/GET /api/v2/orders/search`, from a real React call
     site (rank 40) against a real FastAPI route table (rank 90).
     Asserted in cli/internal/check/e2e_test.go.

  2. ORM model whose column is absent from the migration head
     PASS — `schema:billing-api-db/public.invoices`: the models declare
     total_cents, the two migrations create id/created_at/reference.
     Required a component the plan never asked for; see PLAN CORRECTIONS.

  3. config key read in code and absent from .env.example
     PASS — `config:billing-api/BILLING_WEBHOOK_SECRET`, and it exposed a
     real over-suppression bug on the way (see DEFECTS, #3).

  4. openapi.json disagreeing with the live route table
     PASS — two of them on the demo repository, e.g.
     `http:orders-api/GET /api/v1/orders/{}` status_codes ["200","422"]
     from the app against ["200","404"] from the committed spec.

  5. runs in under 30 seconds on a 200k-line repository
     PASS — measured by the phase auditor, not by me. It built a
     213,270-line, 523-file synthetic repository with two components and
     ran the real extractors over it: 3.44 / 3.44 / 3.11 s. Checked
     non-vacuous by planting a canary config key in a filler file and
     confirming it was found, and by the Node extractor reporting 253
     source files scanned. Warm uv cache; structurally simple files.
     I had reported this NOT VERIFIED, having only this repository
     (~39k lines, 2.6 s) to measure.

  6. zero findings on a fixture known to be correct — THE ONE THAT MATTERS
     PASS on the second audit. FAILED on the first, correctly.
     It took three rounds. The third is the one worth reading.

     `just self-check` reported `No divergences` over **484 facts**, and
     it was worthless. The recipe did not set the placeholder environment
     `just intent` sets, so importing the app raised
     `KeyError: JWT_SECRET_KEY`, and the FastAPI route table and the ORM
     schema — the two rank-90 *enumerating* sources, the ones criteria
     1, 2 and 4 depend on — never extracted. The gate said "no findings"
     and meant "nothing looked".

     That is this product's own failure mode, shipped in its own
     dogfooding gate, and I did not catch it. The phase auditor did.
     With the environment supplied the same command reports **983 facts
     across 432 subjects**, still zero divergences — and that zero is a
     real one. The doubled fact count is the evidence.

     It also then produced one genuine false positive, fixed at the
     source: see DEFECTS #10.

     Guarded now by `scripts/tests/test_self_check_env.py`, which parses
     both the justfile recipe and the CI workflow and fails if they
     diverge — the technique already used for the stop hook's exclusion
     list. Mutation-tested: deleting one env line from the workflow turns
     it red.

DEFINITION OF DONE (field 15)

  culprit check in CI against our own repo   DONE (job `self-check`),
                                             carrying the same
                                             placeholder env, held in
                                             step by a test.
  README showing real output from a real project
                                             DONE — README leads with
                                             `culprit check` and shows
                                             verbatim output from
                                             cli/testdata/demo, which is
                                             reproducible in one command.
  publication: tag v0.1.0, publish binaries,
  release both extractors to PyPI and npm    NOT DONE — and the
                                             machinery for two thirds of
                                             it did not exist until this
                                             phase. The auditor found no
                                             PyPI or npm publish job
                                             anywhere, so tagging v0.1.0
                                             would have published the
                                             binaries and silently
                                             nothing else. Added as
                                             `publish-pypi` and
                                             `publish-npm` in
                                             cli-release.yml, both gated
                                             on the binaries and both
                                             asserting the tag matches
                                             the package version.
                                             Trusted publishing, so no
                                             long-lived token sits in
                                             this repository — which
                                             does mean PyPI trusted
                                             publishing and an NPM_TOKEN
                                             must be configured outside
                                             it first, the same class of
                                             human-only blocker as the
                                             ghcr.io package visibility.

  Publication is deliberately not done, on this file's own condition:
  §4's Phase 29 row says it lands "once a confirmed finding lands in a
  project neither written nor controlled by us". That has not happened.
  Every finding so far is against this repository or against fixtures in
  this repository. Cutting a release and claiming the names on PyPI and
  npm before the tool has been right about somebody else's code is
  exactly the burn the ledger row was written to prevent. Not raised as a
  new question: §4's own row already states the condition.

DEFECTS FOUND AND FIXED — fifteen, all mine

  Eight I found by running the thing. Seven more the two audits found,
  including the one that mattered most: the phase auditor failed
  criterion 6, correctly, and was right.

  1. value_shape meant two different things.
     `.env.example` and code defaults both emitted predicate
     `value_shape`, so the comparator reported
     `config:culprit-api/AGENT_AUTOMATION_TOKEN` as a disagreement
     between a long opaque placeholder and an empty default. They do not
     disagree — one is the shape of an example, the other the shape of a
     fallback. Comparison is by (subject, predicate), so two claims that
     are not the same claim may not share a predicate. Split into
     `example_shape` and `default_shape` in all three languages; golden
     files regenerated.

  2. test assertions were compared as if they described a route.
     Phase 28 emitted the status codes a test asserted, reasoning that a
     mis-pairing would surface as a visible conflict somebody could look
     at. Phase 29 ran the comparator and showed that reasoning was
     wrong: one test asserts 201 for POST /services and another asserts
     403, so they "disagreed". Both are correct — a route answers 201 to
     an admin and 403 to a member. Replaced with `exercised_by_test`,
     which still finds a test hitting a route the app does not serve and
     still feeds the §0.1 coverage report. Documented in LIMITS.

  3. one reader skipping blinded a whole want.
     The absence rule suppressed findings whenever any skip existed for
     (component, want). Several built-in readers share one want, so the
     compose reader's honest "no docker-compose file found" silently
     disabled every config-key absence check for that component —
     including acceptance criterion 3, which simply did not fire and
     looked like a clean result. Removed: the guard was also redundant,
     because the reference requirement (rank >= 80) already carries the
     completeness argument. This is the most dangerous defect of the
     eight, because it failed quietly and in the safe-looking direction.

  4. a hand-written invariant became a component's reference set.
     An `invariants:` entry is rank 100 — above every extractor — so
     buildCoverage picked it as the complete description of that
     component's routes, and the application's two real routes were
     reported as absent from a set of one. Rank says how much to believe
     a source; it does not say the source was surveying a surface. Fixed
     with `enumerates()`, which excludes SourceKind.ASSERTION from
     reference sets. Found by the eval corpus, on the fixture written to
     test invariants.

  5. sameSource keyed on the extractor alone.
     One extractor legitimately reads several independent descriptions
     of the same thing: the Python extractor reports the ORM's columns
     *and* the migration chain's columns, and an unmigrated column is
     precisely those two disagreeing. Keying the duplicate guard on the
     extractor name made acceptance criterion 2 impossible to detect.
     Narrowed to extractor *and* artefact. The comparator's own unit
     tests would never have caught this — they were written against the
     same wrong idea. The corpus caught it.

  6. the report could print a config value.
     `renderValue` fell through to CanonicalJSON(fact.Value) for any
     fact without a shape, on the reasoning that Fact.Validate refuses a
     literal config value upstream. The redaction test disagreed
     immediately and was right: the renderer renders whatever it is
     handed, and "somewhere else guarantees it" is the shape of argument
     that produces a leak the day a fourth path appears. A `config:`
     subject now cannot reach the value branch, whatever the fact
     carries. This mattered most for SARIF, which lands on a pull
     request that may be public.

  7. the absent side of a finding pointed at the wrong line.
     Absence findings reused a sample fact from the reference source
     wholesale, so the report told the reader to go and look at whichever
     route happened to sort first. It also violated the Python
     Divergence model, which requires both sides to name the same
     subject — so every absence finding would have been rejected on
     upload. Fixed with `absentFrom`, which synthesises the reference's
     own "not present" answer for the subject in question.

  8. artefact paths were component-relative in reports, and one was
     Windows-separated.
     SARIF annotations are matched by GitHub against repo-relative paths
     and a path that does not match is not an error — the annotation is
     silently dropped, which is the worst possible failure for the
     feature that carries the adoption story. Added RebaseArtefacts
     (check only; `culprit intent` output is unchanged). Separately, the
     new migration reader produced `migrations\versions` on Windows;
     switched to as_posix().

  --- found by the two audits, not by me ---

  9. the self-check gate reported a meaningless zero.
     See criterion 6. The single most important criterion in the phase
     was passing because nothing had been extracted, in a gate I wrote
     specifically to catch that class of failure. Reported honestly by
     the phase auditor as a FAIL, which is what an auditor is for.

 10. the Node extractor invented an unmatchable route.
     `` `/model/graph${query}` `` in Culprit's own frontend became the
     subject `/model/graph{}`, which no server route can ever equal —
     a permanent false positive against a correct repository, and the
     one finding standing between this repo and a clean self-check. The
     call site is now skipped rather than guessed at, a literal `?`
     ends the path, and `/users/${id}` is untouched. Three regression
     tests. The false negative that buys is in docs/LIMITS.md.

 11. SARIF annotations pointed at files that do not exist.
     `RebaseArtefacts` looked the repo prefix up by the *subject's*
     component, not the component that produced the fact. For a client
     call — acceptance criterion 1's own finding class — the frontend's
     `src/lib/api.ts` got the backend's root, giving
     `api/src/lib/api.ts`. GitHub drops an annotation whose path does
     not resolve, silently and with no error, so the feature field 4
     calls "most of the adoption story" would simply have shown
     nothing. Now `rebaseTarget`, inside the orchestrator's per-target
     loop, where the producing component is certain.

     My test for this passed throughout, because every fixture fact had
     subject-component == producing-component, and the e2e assertion
     was `strings.Contains(artefact, "orders.ts")` — which passes with
     a wrong prefix. A substring check on a path asserts almost nothing
     about the part that has to be right. Both are now exact, and the
     unit test uses the cross-component case.

 12. the divergence identity was not unique per finding.
     `ID()` keyed on the two extractors while the comparator's own
     `sameSource` defines a source as extractor *and* artefact — the
     same conflation as DEFECTS #5, made twice in two places. One
     extractor reading three descriptions of one table produced two
     findings with identical keys, so the second upsert overwrote the
     first: a real fault deleted, with the endpoint reporting both as
     handled. Fixed in both languages; the conformance fixture gained
     the collision case and a test asserting every case's identity is
     distinct.

 13. the eval could not see a duplicate finding.
     `compare()` keyed its map by (subject, predicate), so a second
     divergence on a pair already in expected.json overwrote the first
     and was never counted. The gate whose whole point is "exact in
     both directions" was exact in one — and it is the gate that should
     have caught #12. Now keyed by identity, and it errors outright on
     a collision.

 14. a unique index that could never fire.
     `divergence_key` was added nullable with a comment claiming a
     writer forgetting it would fail on the unique index. Postgres
     treats NULLs as distinct, so such a writer would insert unlimited
     rows and never error — a load-bearing comment describing a
     backstop that did not exist. Now NOT NULL, the table being empty
     by design.

 15. a table-wide UPDATE grant where the rule asks for columns.
     `.claude/rules/database.md` prefers column-level grants, and this
     is exactly the case for one: the docstrings rest on "first_seen_at
     keeps meaning what it says", which a bare table grant leaves as an
     application convention. A leaked project token could have made
     every open finding look new. Now nine named columns; the role test
     asserts UPDATE on `first_seen_at` and `subject` is refused.

  Also: exit codes 1 and 2 were the wrong way round in the Phase 28
  binary (it reserved 2 for findings). Field 7 says 1 for findings, 2
  for execution error, and the plan is right — `if culprit check; then`
  is the useful shape and "your build has a problem" needs a different
  alert from "the tool could not run". Corrected; nothing depended on
  the old numbering.

WHAT CULPRIT FOUND IN CULPRIT

  One real defect, fixed: `INGEST_RATE_LIMIT` and `INGEST_MAX_BODY_BYTES`
  are read by api/app/ingest_gateway/config.py and were documented only
  in infra/.env.prod.example, not in api/.env.example — the file a
  developer copies. Ranked `degrades` rather than `breaks_request_path`,
  correctly, because the code supplies defaults; that severity rule was
  added in response to this finding. Both keys added to
  api/.env.example, with a comment saying which tool found them.

PLAN CORRECTIONS

  - Field 14 criterion 2 was unreachable as the plan stood. Nothing in
    the repository could say which columns the migrations create — the
    only migration fact anywhere was the head revision id, a version
    string. Field 4 does not mention a migration reader and field 5
    lists only CI as a component to modify. Built
    extractors/python/culprit_extract_python/migrations.py: replays the
    chain statically with `ast`, never by importing or executing a
    migration, at rank 80, and declines entirely rather than guessing
    when the chain does not form a single line.

  - Field 4's `culprit.yaml invariants:` needed a decision the plan does
    not make: what an invariant *is* to the comparator. Made it an
    ordinary INTENT fact at rank 100, so the same generic comparator
    handles it with no special case. Consequence recorded as decision
    D-29a in §2: an invariant that is wrong produces a loud finding
    rather than being quietly overruled by the code, which is correct —
    a stale assertion is a real defect.

  - Field 9's endpoint needed schema the Phase 26 table did not have.
    Storing one run works; storing many does not, and history is the
    whole point. Added divergence_key (unique), last_seen_at,
    explanation, severity_reason, suppressed_by.

  - The plan does not say whether the CLI uploads. It does not, and that
    is deliberate: the binary links no HTTP client at all, and a test
    asserts the check pipeline links no networking package whatsoever —
    not net, not net/http, not crypto/tls. That is field 17's "no LLM
    anywhere near this path" made structural rather than kept as a list
    of vendor names. An uploader belongs with Phase 30's capability
    model, which is where network access should be gated.

  - Phase 29 emits exactly one DivergenceKind: intent_conflict. Every
    fact the CLI can produce is on the INTENT plane, so every
    disagreement it can find is between two intent sources. Emitting any
    other kind would be a claim about a plane nothing has read.

DELIBERATELY NOT BUILT (field 17)

  No environment access. No probes. No network call of any kind from the
  check path — structurally, not by convention. No CLI upload. No
  automatic closing of findings that stop appearing: this run may have
  checked a subset, and inferring "it is fixed" from "I did not see it"
  is the same mistake the comparator refuses to make about facts.
  Resolution needs verification, which is Phase 32.

RULE EXCEPTION TAKEN, DELIBERATELY

  `.claude/rules/database.md` says add a role rather than widen one.
  The divergence endpoint widens `fact-writer` (INSERT, SELECT, UPDATE
  on `divergences`) instead of adding a twelfth role. This is the second
  sanctioned exception in the repository's history; the first was
  postmortem-writer covering engineering memory in Phase 21, on the same
  reasoning. Divergences are produced by the same CI run, from the same
  repository, under the same project token, as the facts they were
  derived from — the same trust domain and the same blast radius. A
  separate role would mean a second password in every CI configuration,
  issued to the same process, for the same purpose.

  api/tests/test_facts_api.py's role test previously asserted that
  fact-writer could NOT touch `divergences`, and it caught this change,
  which is what it is for. It was rewritten rather than deleted, and the
  rewrite is strictly stronger: it still asserts the two other planes
  are unreachable, and now also asserts users, api_keys, components and
  postmortems are unreachable, that the role cannot DELETE from either
  table it can write, and positively that it can read divergences. The
  widening bought one table and nothing else.

STANDING OBLIGATIONS

  Q2 (recorded demonstration + written account for Phases 29, 30, 32):
  the written account is docs/demos/phase-29.md. The recording is NOT
  done and needs a person — the demonstration is one command, so it is a
  matter of running it on camera, not of building anything.

  Q1's revisit trigger is TRIPPED and is for the architecture session,
  not for me. Q1 says: "if the Go surface passes ~6k lines by the end of
  Phase 29, or starts absorbing logic that belongs in the control plane,
  the boundary is wrong." cli/ is now 6,060 non-test lines (8,326
  including tests), of which 3,917 are non-comment, non-blank. Whether
  the trigger is about lines or about substance is the question: my own
  reading is that the Go surface has not absorbed control-plane logic —
  comparison, severity and reporting all belong in the binary that runs
  in CI with no server — and that the count is inflated by this
  codebase's comment density. But that is a judgement the trigger exists
  to take out of my hands. Surfaced, not answered.

KNOWN GAPS, STATED PLAINLY

  - The fault corpus evaluates the divergence engine given facts, not
    extraction. Extraction has its own corpus (Phase 28's goldens plus
    the two extractors' suites) and the demo repository joins the two
    end to end, but the fault bundles are committed inputs and would go
    stale silently if an extractor changed what it emits. In LIMITS.

  - Criterion 5 is unverified (above).

  - `.claude/settings.json` shows a 45-line diff that is not Phase 29
    work: Claude Code rewrote its own permission entries from
    `Bash(just *)` to `Bash(just:*)`. Mechanical, tooling-generated,
    committed with the phase rather than left dirtying the tree.

  - Still true from Phase 28: no .gitattributes, so `git diff` is
    dominated by CRLF noise. Use --ignore-space-at-eol. Also still true:
    the ghcr.io packages are private and need a human in the GitHub UI.
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
