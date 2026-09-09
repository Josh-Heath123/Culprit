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

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) |
| Current phase | **27 — The system model (the circuit)** |
| Status | Ready to start. 26.1 complete, pending its commit. |
| Branch | `phase-26-truth-repair` (26 committed as `d39ca3b`; 26.1 staged). **`main` is two branches behind — merge before starting 27.** |
| Blocking questions | **None.** Q1–Q5 all resolved (§3). |
| Last gate run | 2026-09-09, all green (§5) |

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

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | **complete** | Signed off 2026-09-09. All five acceptance criteria met (criterion 1 as reworded). Verification quality was the bar for every phase after this one. |
| 26.1 | `configured_facts` value safety | **complete, pending commit** | Signed off 2026-09-09. Caught two defects in the brief itself: the CHECK as specified would have inverted its own intent against `value NOT NULL DEFAULT 'null'::jsonb`, and the guarantee was narrower than §2.2 claimed. Both corrected. |
| 27 | The system model (the circuit) | current | Merge `main` first. Two small additions in field 4 before the model work: the CI migration round-trip job (invariant 8) and `scripts/check_scan_coverage.py` (invariant 9) — both close gaps Phase 26.1 exposed, and every phase after this ships migrations. Then the model itself: data migration must not lose anything on an existing deployment, `culprit.yaml` must round-trip, `contract_id` stays null throughout. |
| 28 | CLI, extractor protocol, intent extraction | not started | Blocked on Q1. |
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
Phase:        26.1 — configured_facts value safety (the §4 prerequisite to 27)
Branch:       phase-26.1-configured-facts-value-safety (off d39ca3b)
Started:      2026-09-09
Finished:     2026-09-09

Scope note:   /next advanced ONE ledger row. Phase 27 was NOT started. 26.1's
              own brief says "own branch, own commit", which is a second
              review checkpoint by construction, and §1's rule is that Claude
              Code does not auto-start the next phase.

Gates:        (from /verify, re-run independently by phase-auditor)
  lint            PASS   (api+shared+scripts, worker, demo-services, mcp_server)
  typecheck       PASS   (0 errors x4)
  lint-imports    PASS   (4 contracts kept)
  schema-drift    PASS   (16 worker tables match api's ORM)
  tests           PASS   (api 426 (+5), worker 86, mcp_server 21; 3 skipped)
  coupled-files   PASS   (the declared pair both changed)
  no-llm-imports  PASS   (6 deterministic packages)
  migration-sym   PASS   (3 files)

Acceptance criteria (phase-auditor, executed not inferred — all MET):
  1. Migration applies from an empty DB and produces exactly the specified
     shape
       MET. Fresh timescaledb-ha:pg16 container, alembic upgrade head ->
       a3d81f6c4b27. value jsonb nullable, no default; value_shape jsonb
       nullable; grant_ref varchar nullable; CHECK ((value IS NULL) OR
       (grant_ref IS NOT NULL)) present under the expected name.
  2. The DATABASE does the rejecting, not application code
       MET, three ways. The test file imports no app.* module and inserts
       via raw sa.text() on the superuser engine. The auditor reproduced
       the rejection under a different driver (psycopg2, no pytest, no
       conftest) and got CheckViolation. And the mutation test — remove
       create_check_constraint, re-run — gives 2 failed / 3 passed, both
       failures "DID NOT RAISE IntegrityError". Run twice independently
       (once by me, once by the auditor), file restored byte-exact both
       times, md5 verified.
  3. The five tables are still empty, and no role can write them
       MET. After a fresh migration: captures 0, intent_facts 0,
       configured_facts 0, readings 0, divergences 0.
       information_schema.role_table_grants and column_privileges over all
       five, excluding superuser and PUBLIC, return zero rows. All ten
       roles exist; none holds a grant. The migration contains no
       GRANT/REVOKE.
  4. "Nothing else" — scope discipline
       MET. Diff vs d39ca3b: api/app/db/models.py, worker/app/db.py, the
       new migration, the new test, and docs. shared/culprit_model/
       untouched; no components/connections work begun.

Definition of done:
  Migration + test               MET
  docs/LIMITS.md updated         MET
  Committed                      NOT DONE. `git commit` was denied at the
                                 permission prompt — the same thing that
                                 happened at the end of Phase 26. Nothing is
                                 even staged: the denial covered the whole
                                 `git add -A && git commit` command. The work
                                 sits in the working tree of
                                 phase-26.1-configured-facts-value-safety and
                                 is exactly what every gate above was run
                                 against. Re-running the commit is the one
                                 step left. Not retried without approval.
  Merged to main                 NOT DONE, deliberately — the human review
                                 checkpoint. Note Phase 26 is also still
                                 unmerged, so main is two branches behind.

Built:
  - api/migrations/versions/a3d81f6c4b27_configured_facts_value_safety.py:
    adds value_shape (JSONB) and grant_ref (String), drops value to
    nullable and removes its server default, adds
    ck_configured_facts_value_requires_grant.
  - api/tests/test_configured_facts_value_safety.py — 5 cases: ungranted
    literal rejected, JSON-null-without-grant rejected, shape-without-value
    accepted, granted value accepted, grant-without-value accepted.
  - The coupled pair api/app/db/models.py + worker/app/db.py, kept in sync
    including nullability.
  - docs/LIMITS.md, CLAUDE.md status + architecture point 18.

Plan corrections — things the brief could not have known:
  1. THE CONSTRAINT AS SPECIFIED WOULD HAVE INVERTED ITS OWN INTENT.
     §2.2 and the §4 brief both say to add CHECK "value IS NULL OR
     grant_ref IS NOT NULL". But c07a5f31d8e4 created value as NOT NULL
     DEFAULT 'null'::jsonb, and 'null'::jsonb IS NULL is FALSE in SQL — so
     adding that constraint verbatim would have required a grant_ref on
     EVERY row, making the ordinary shape-only fact unrepresentable and
     the granted-secret row the only legal one. The migration therefore
     also drops value to nullable and removes the default, so SQL NULL is
     the "no value stored" state. This is a real defect in the plan's
     instruction, not a liberty taken with it.
  2. §2.2's claim is broader than what the specified schema delivers.
     Written up as Q5 in §3. The CHECK protects value; value_shape,
     which is where the design sends extractors, is unconstrained JSONB
     and will accept a literal secret. Not fixed here (outside "nothing
     else"); the migration docstring and docs/LIMITS.md were narrowed to
     claim only what is true.

Found and fixed en route:
  - A round-trip defect in my own first draft of the migration, found by
    replaying upgrade -> downgrade -> upgrade against a real database with
    rows present. downgrade() rewrites SQL NULL to 'null'::jsonb to restore
    NOT NULL; on re-upgrade those rows then looked like ungranted literal
    values and ADD CONSTRAINT failed. Fixed by normalising 'null'::jsonb
    back to SQL NULL in upgrade(). Worth noting for future phases:
    check_migration_symmetry.py passed this migration both before and
    after the fix — it is structural and cannot see this class of bug. A
    real down/up replay is the only thing that catches it.

From the invariant audit (1 low violation, 5 risks; no gate broken):
  Fixed here:
  - V1: the test hand-formatted a subject URI
    (config:orders-svc/DATABASE_URL). It escaped
    scripts/tests/test_subject_construction.py only because api/tests is
    outside that check's scanned roots — an exemption by accident, and
    shared/tests IS scanned, so the repo's precedent runs the other way.
    Now built with subjects.build().
  - R1/R4: overreaching claims narrowed in the migration docstring and
    docs/LIMITS.md (see Q5), and the silent half of the downgrade's data
    loss documented — downgrade() also drops value_shape, which after
    Phase 27 IS the payload of a CONFIGURED fact, so a down/up cycle
    succeeds and leaves contentless facts behind. The granted-value half
    fails loudly and was already documented; this half did not announce
    itself.

  Surfaced, deliberately NOT fixed — all outside the "nothing else" brief,
  and each one wants a decision rather than a guess:
  - R1: value_shape needs a closed key vocabulary. This is Q5.
  - R2: grant_ref = '' satisfies the constraint. Also Q5. Separately,
    readings.grants_used (JSONB array) and configured_facts.grant_ref
    (scalar string) are now two unrelated spellings of "grant" with no
    stated relationship — worth pinning the identifier format before
    Phase 31 builds on both.
  - R3: shared/culprit_model/facts.py still has value: Any = None with no
    value_shape, no grant_ref and no validator. Postgres is the only
    enforcement point, so a Fact constructed and serialised WITHOUT being
    inserted — which is exactly what a Phase 30 capture bundle is — is
    unprotected. .claude/rules/model.md asks for safe-by-construction;
    that is now true of the DB write path and still untrue of the model
    layer. Nothing checks this pair (check_schema_drift.py compares
    worker<->api only). Phase 27 or 30 should close it.
  - R5: the constraint lives only in the migration. worker tests that
    build schema with metadata.create_all would not have it, and
    check_schema_drift.py compares columns only. Pre-existing house style
    (ck_configured_facts_source_kind is migration-only too), so 26.1 adds
    no new drift — flagged because this is the first such constraint whose
    absence would be a security property going missing rather than a
    validation rule.

Blocked on:  The commit itself, denied at the permission prompt. Every gate
             is green against exactly the tree that is sitting there
             uncommitted.
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
