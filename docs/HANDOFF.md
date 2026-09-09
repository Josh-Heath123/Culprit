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
| Current phase | **26 — Truth repair and the three-plane schema** |
| Status | Complete on branch, **staged but not committed** — the commit was denied, see §5 |
| Branch | `phase-26-truth-repair` (all 47 files staged via `git add -A`) |
| Blocking questions | 4 open (§3) — none block Phase 26; Q1 blocks Phase 28, Q3 blocks Phase 30 |
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

---

## §3. Open questions

Claude Code must not answer these. It surfaces them and stops.

**Q1 — Is Go acceptable for the CLI and probe agent?** (Blocks Phase 28.)
`docs/DIAGNOSTIC_PLAN.md` D2 chooses Go for a single static binary, because
`pip install` at the first-run moment is friction where it costs most. The cost
is two languages in one repo for a small team. Fallback if no: a Python CLI
distributed via PyInstaller — worse distribution, no rewrite. **Decide before
Phase 28 starts, not midway through it.**

**Q2 — Product or portfolio piece?** (Affects ordering from Phase 30 on.)
As written, the phases optimise for a usable product early: Phase 29 ships
something a stranger can run. If the priority is a portfolio artefact, Phases 31
(probes) and 32 (fault isolation) are the impressive ones and Phase 30 could be
deferred behind them.

**Q3 — Should `configured_facts` structurally prevent storing config
*values*?** (Raised by the Phase 26 invariant audit. Blocks Phase 30.)
`.claude/rules/model.md` says facts carry config "names and shapes, never
values, unless an explicit per-key grant applies… and there is a test asserting
it." Phase 26 landed `configured_facts` with a free-form `value` JSONB: no
`redacted` flag, no `value_shape` column, no constraint. Nothing is wrong today
(the table is empty and no extractor exists), but the only thing that will keep
a raw `DATABASE_URL` out of it once Phase 30 writes captures is extractor
discipline — the schema will not object. Cheapest to decide now, while the table
is still empty. Options: a `redacted boolean NOT NULL DEFAULT true` column; a
separate `value_shape` column with `value` reserved for granted keys; or a
documented convention plus the asserting test the rule already demands.

**Q4 — Phase 26's acceptance criterion 1 is untrue as literally worded.**
(Does not block anything; needs a wording decision.) It reads "A revoked ingest
key is rejected on the very next request." The gateway serves an in-memory key
map refreshed at most once per `_MIN_RELOAD_INTERVAL_S` (10s), so the literal
next request inside that window still authenticates, and making it literally
true means removing the cache — a per-request database round trip on the ingest
hot path, which the design rejects for good reason. What Phase 26 actually
fixed, and what the regression test asserts, is that revocation now takes
effect *at all*: it used to require an unrelated unknown-key request to trigger
the reload, which for an attacker holding a just-revoked key is never.
Suggested rewording: *"A revoked ingest key stops authenticating within
`_MIN_RELOAD_INTERVAL_S` (10s), on the first request after that interval
elapses, with no intervening unknown-key request required."* Recorded rather
than applied — Claude Code does not edit the plan's criteria.

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | complete (on branch) | Start here. Deliberately the smallest and most mechanical phase — a good shakedown for the whole toolchain. Do the `CLAUDE.md` repair *first*, before any code: every session until it lands pays for the stale version. |
| 27 | The system model (the circuit) | not started | — |
| 28 | CLI, extractor protocol, intent extraction | not started | Blocked on Q1. |
| 29 | The divergence engine | not started | First shippable product. This is the wedge — treat its acceptance criteria as the real bar, especially "zero findings on a fixture known to be correct". |
| 30 | Environment capture and cross-env diff | not started | — |
| 31 | Probes | not started | — |
| 32 | Fault isolation and the Investigation | not started | — |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

---

## §5. Last run

Claude Code overwrites this section at the end of every `/next`.

```
Phase:        26 — Truth repair and the three-plane schema
Branch:       phase-26-truth-repair
Started:      2026-09-09
Finished:     2026-09-09

Gates:        (from /verify)
  lint            PASS   (api+shared, worker, demo-services, mcp_server)
  typecheck       PASS   (0 errors x4, api's now covers ../shared too)
  lint-imports    PASS   (4 contracts kept, incl. the new culprit_model one)
  schema-drift    PASS   (16 worker tables match api's ORM)
  tests           PASS   (api 421, worker 86, mcp_server 21; 3 skipped)
  coupled-files   PASS   (working tree and --base origin/main)
  no-llm-imports  PASS   (new gate; 6 deterministic packages)
  migration-sym   PASS   (2 files — see "Plan corrections" on why that number
                          used to be 0)

Acceptance criteria (from phase-auditor, executed not inferred):
  1. Revoked key rejected on the very next request
       MET AS FIELD 5 SPECIFIES IT / NOT MET AS LITERALLY WORDED.
       The auditor mutation-tested this: a throwaway subclass restoring the
       old reload-on-miss authenticate() returns "checkout-api" for the
       revoked key in the exact scenario where the fixed store returns None,
       so the regression test is genuinely discriminating and the security
       fix is real. But the literal next request inside the 10s cache window
       still authenticates, and always will unless the cache goes. See Q4 in
       §3 — the criterion needs rewording, not the code changing.
  2. Every service refuses to start with an unset *_DATABASE_URL
       MET. Verified by starting real processes, not by importing modules:
       uvicorn (api, and ingest_gateway separately), arq (worker), and
       python -m mcp_server each exit 1 with a message naming the missing
       variable, once per variable, with an all-set control that starts.
  3. `just quickstart` still produces an incident end to end
       MET, and verified twice independently. Incident opened with
       anomalies from the injected latency fault across
       inventory-service/order-service/payments-service, fetched back
       through the authenticated API. No root-cause narrative, which is the
       documented quickstart default (VOYAGE_API_KEY is empty), not a
       regression. This criterion failed twice before passing — see
       "Plan corrections" below.
  4. `alembic upgrade head` from an empty DB using only .env.example
       MET. Fresh timescaledb container, no api/.env on disk, env sourced
       from .env.example verbatim including every change-me-* value; 20
       migrations applied through c07a5f31d8e4. Also verified the reverse:
       downgrade to beab08d5f92f and back up again, both clean.
  5. CLAUDE.md describes the repository as it actually is
       MET, after the auditor found two false statements that survived the
       first rewrite ("Phases 13-20, current work", and "one Postgres
       instance, two roles" contradicting the same file's own "ten roles").
       Both fixed. All 28 justfile recipes it names exist; every path it
       cites exists; architecture point 18 matches reality.

Definition of done (field 15):
  All of field 14                   MET (given the Q4 rewording)
  docs/LIMITS.md updated with the
    Phase 23 linking heuristic      MET — plus five other new sections
  Committed                         NOT DONE. `git commit` was denied by the
                                    permission prompt. All 47 files are staged
                                    (`git add -A` succeeded); the tree is
                                    exactly what the gates above were run
                                    against. Re-running the commit is the one
                                    step left before review.
  Merged to main, deployed          NOT DONE, deliberately. /next stops at the
                                    branch; merging is the human review
                                    checkpoint this file exists to create.

Field 17 (do NOT implement yet):   RESPECTED, verified by execution.
  No cli/, no extractors/, no probes/. shared/culprit_model/ contains
  exactly the five files field 4 names. All five new tables are empty after
  a fresh migration AND after a full quickstart run with live telemetry,
  anomalies and an incident. information_schema.role_table_grants for those
  tables returns zero rows excluding the superuser — no least-privilege role
  could write them even if code tried.

Built:
  - shared/culprit_model/ (planes, facts, subjects, canonical) inside the
    existing culprit-shared distribution, so api and worker already have it.
    subjects.build() is the only sanctioned subject constructor; hand-
    formatting one anywhere else now fails scripts/tests/test_subject_
    construction.py (verified by planting a violation — it fired).
    shared/tests/subject_conformance.json is the shared fixture Phase 28's
    Go implementation will be held to, written before that implementation
    exists on purpose.
  - Two migrations: c07a5f31d8e4 (captures, intent_facts, configured_facts,
    readings as a 1-day-chunk hypertable with 7-day compression and 90-day
    retention, divergences) and b41c7d9e02a5 (the two missing HNSW indexes
    on architecture_decisions.embedding and ai_change_records.embedding).
    Three invariants are encoded in the schema rather than left to code:
    intent_facts has no environment column, captures has a check constraint
    tying environment to plane, and readings requires a reason whenever the
    verdict is inconclusive or refused.
  - scripts/check_no_llm_imports.py + `just check-no-llm-imports` + a CI
    step. Two tiers: nothing deterministic may import a chat client;
    everything except mcp_server may not import an embedding client either
    (mcp_server legitimately embeds to search memory, and its own AST test
    proves the Voyage client is only ever .embed()-ed).
  - Security fix: api/app/ingest_gateway/auth.py reloads before the lookup,
    not only after a miss. A revoked key hashes to a hit, so it never
    triggered the miss-reload that would have removed it — revocation did
    nothing until an unrelated bad-key request happened along.
  - Fail-open removal: the four api config modules, worker/app/main.py's
    four DB URLs, and worker/scripts/seed_postmortems.py all lost their
    committed <role>-dev-password fallbacks. `grep -rn "dev-password@"`
    across the repo now returns nothing outside the test asserting it.
  - worker/app/consumer.py quarantines unparseable entries to a `dead-letter`
    Redis stream and acks them, instead of one bad message wedging the drain
    forever and silently stopping every valid message behind it.
  - worker/app/rag/job.py verifies each cited passage is a real substring of
    the postmortem it is attributed to, drops the ones that are not, and
    reports the count. A fabricated quotation used to be stored and rendered
    indistinguishably from a real one.
  - scripts/bootstrap_env.py's IMAGE_REGISTRY, api/.env.example's four
    missing role passwords, CLAUDE.md's status and architecture sections,
    docs/LIMITS.md.

Deliberately not built (field 17):
  Extractors, probes, the CLI, and any code that writes the five new tables.
  They are created empty and stay empty until Phase 27.

Plan corrections needed:
  1. Acceptance criterion 1 is untrue as literally worded and cannot be made
     true without removing the ingest key cache. Written up as Q4 in §3 with
     a suggested rewording. Not edited here — Claude Code does not rewrite
     the plan's criteria.
  2. Field 5 under-specifies criterion 2. It names four api/app/*/config.py
     modules, but the criterion says *every service*, and worker/app/main.py
     had the same four fail-open defaults. Fixed the worker too, plus
     seed_postmortems.py, which the invariant audit found holding the last
     committed credential in the repository.
  3. `docs/DIAGNOSTIC_PLAN.md` §2.5 names the Divergence fields `left` and
     `right`. Both are reserved words in Postgres, so the columns are
     `left_fact`/`right_fact`. The model keeps the plan's names.

Found and fixed en route, none of it in the plan (all pre-existing):
  - `just quickstart` was broken on a clean checkout: it builds the frontend,
    whose api-types.generated.ts is gitignored and generated by
    `just generate-types`, which quickstart never runs. And generate-types
    itself needed a hand-written api/.env. It now supplies its own dummy
    values, the way CI already did.
  - `just quickstart` builds every service EXCEPT bootstrap, so `run --rm
    bootstrap` reused whatever image the machine already had. On this machine
    that was a 2026-08-05 image with 13 migrations: the quickstart left the
    database at fbf4cb16570a (Phase 16) while every other container ran
    current code — exit 0, no error anywhere. Silent since Phase 17 on any
    machine that had run quickstart before; invisible on a fresh one. Fixed
    with `--build`.
  - `scripts/check_migration_symmetry.py`'s no-argument mode diffed only
    against `main`, so on a branch whose migrations were uncommitted it
    checked zero files and printed a pass. It now includes the working tree,
    the way check_coupled_files.py already did.

From the invariant audit (verdict: clean on every enforced invariant),
fixed here:
  - subjects.build() accepted parts containing its own separators, so
    build("http", component="ns/orders", ...) produced a subject that parsed
    back as a different component without raising — the exact silently-
    mangled subject its own SubjectError docstring warns about. Now rejected,
    with seven cases added to the shared conformance fixture so Phase 28's Go
    implementation inherits the rule.
  - The reload-before-lookup fix stamped _last_reload_at only on success, so
    a Postgres outage made every request due for a reload, each paying a
    connection timeout behind one lock — turning a database blip into total
    ingest unavailability, which the old code was accidentally immune to.
    Now stamped on attempt, failure logged and swallowed.
  - Dead-lettering an entire failed batch would push real telemetry through
    a 10k ring buffer within minutes at any real ingest rate. A wholly
    unparseable batch now raises instead of acking — the old recoverable
    wedge, kept deliberately for the one case where it is right. The
    quarantine count is also carried into the job's return value so it
    reaches the span and structured log, not just a format string.
  - Citation verification keyed on postmortem title, which has no unique
    constraint; a duplicate title would drop a real citation as fabricated.
    Now checks every retrieved postmortem sharing that title.
  - check_no_llm_imports.py walked .venv directories (no listed package had
    one until mcp_server was added).

One more pre-existing gap, found by the fast_gates hook at the end:
  `just lint` covered api/worker/demo-services/mcp_server but not
  `scripts/`, while .claude/hooks/fast_gates.sh lints every changed Python
  file wherever it lives. The hook was stricter than the gate, and had
  three real pre-existing violations waiting in scripts/bootstrap_env.py
  and scripts/check_schema_drift.py. `scripts/` now rides along on api's
  ruff the same way `shared/` does, in both the justfile and CI.

Blocked on:  The commit itself — denied at the permission prompt. Work is
             staged and every gate is green against exactly what is staged.
```

---

## §6. Escalate to the architecture session when

Do not guess on any of these. Stop, write the question into §3, and stop.

- The plan's stated interface, data model or acceptance criterion turns out to be
  wrong or under-specified against the real code.
- Implementing a phase appears to require something on its own field-17 list.
- A gate can only be made green by weakening it — widening a `lint-imports`
  contract, adding a `# type: ignore`, skipping a test, widening a Postgres role.
- A decision in §2 would have to be reversed.
- Two intent sources disagree in a way the plan does not describe how to rank.
