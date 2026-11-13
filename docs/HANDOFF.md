# Handoff — the baton between architecture and execution

This file is the state carrier for Culprit's development. It exists because the
architecture conversation and the implementation session are different places,
and a decision that lives only in a chat transcript is a decision that gets made
twice.

**Protocol.**

- **The architecture session writes** the *Brief* line of the current phase in
  §4. It never writes run reports.
- **Claude Code writes** §4 status transitions and §5 (Last run). Where a brief
  is wrong or under-specified against the real code, it surfaces that and stops
  (§6) rather than deciding it.
- **The decisions register was retired 2026-09-12.** Decisions of record are
  `docs/DIAGNOSTIC_PLAN.md` §1 (D1–D8, with their dated amendments) and §3's
  standing invariants; their history is `git log` on both files.
- **§3 is an inbox of open questions, restored 2026-11-03.** Unresolved items
  only. Claude Code adds one when it escalates (§6) and stops on any marked
  blocking; the architecture session deletes it when answered and records the
  answer in the plan. It came back because without it, a question raised in a
  run report — the D2 revisit trigger — had nowhere to live and was dropped.
- **Phases land on `main` through a pull request** (2026-11-05). Its run on the
  merge result is the gate; a direct push changes `main` before anything has
  run. Claude Code pushes the branch, opens the pull request and runs `/ci`;
  the human merges it, after the architecture review, when every check is green.
- **Both read the whole file first.**

**CI is part of the gate set.** A phase is not complete until CI is green on the
**merge result** — `origin/main` merged into the branch — not on the branch
alone. Local `/verify` covers neither: it runs a subset of the checks, on a tree
that is not what gets merged, on Windows rather than Linux. Run `/ci` before
reporting any phase complete.

**Committing and pushing — Claude Code does it; merging — only the human**
(changed 2026-11-06, Malcolm's decision). Claude Code commits its own work on
the phase branch with `git commit -F <message-file>`, pushes that branch, opens
the pull request with `gh pr create`, and runs `/ci` on it. It never pushes to
`main`, never force-pushes, and never merges or approves a pull request: the
merge is the human's, after the architecture review, and it is the one
checkpoint this protocol keeps. (The earlier refusals of `git commit` and
`git push` were most likely this file and `CLAUDE.md` saying the human commits,
which auto mode reads as a boundary, together with `ask` rules on `git push`
and `gh pr create`. Both changed together.)

**The pull request is a draft until the run has finished** (2026-11-11). Claude
Code opens it with `gh pr create --draft` and marks it ready with `gh pr ready`
only when its run report is committed and pushed, as the last thing before it
stops. A draft cannot be merged, so a merge can no longer land ahead of the run.
That is what happened to Phase 35 part 2: it was merged while its re-audit was
still fixing things, and those fixes were left on the branch. Before every push
it checks `gh pr view --json state`. If the pull request is already merged, it
pushes nothing more to that branch and stops and reports what is not on `main`.

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/PERFORMANCE_PLAN.md` (Phases 36–39). `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) is complete; its D1–D8 and standing invariants still bind. |
| Current phase | **37, part 3 — The database in the walk** — `not started`. Brief: `docs/PERFORMANCE_PLAN.md`, end of Phase 37, "Part 3". Step 0: `main`'s push run on `1b2496b` green. Item 1 carries in Q31 (probes declare their verdicts), Q32, A2 and the statistics deadline. |
| Previous phase | **37, part 2 — Statements and plans: signed off 2026-11-13** by the architecture session. It is complete when `main`'s push run on `1b2496b` is green. PR #41 merged as `1b2496b`; the pull request's runs 43380877940 and 43390113268 were green on every job, read from GitHub. The mid-run rulings, Q31 and Q32 are recorded at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-37-walk`, to be cut from `origin/main` = `1b2496b`. Its first commit is the part 2 sign-off, already in the working tree (`docs/PERFORMANCE_PLAN.md`, `docs/HANDOFF.md`; message `../phase-37-2-signoff.txt`). Open a draft pull request and mark it ready when the run report is committed. Do not stage `shared/uv.lock`. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q31 and Q32 were ruled on 2026-11-13 (`PERFORMANCE_PLAN.md`, end of Phase 37). Q31: every probe declares the verdicts it can give, readings are validated against that declaration, and the fixture gate requires one fixture per declared verdict, with no names. Q32: statement text is kept only on PostgreSQL 16 and later, and CI checks `SELECT … INTO` on 16. Both are built in part 3. | | |

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
| 29 | The divergence engine | **complete** | Merged (PR #16). Publication still deliberately not done — §4's own condition (a confirmed finding in a project neither written nor controlled by us) has not been met. |
| 30 | Environment capture and cross-env diff | **complete** | Signed off 2026-09-12. Both audits clean 2026-09-10; the deploy failure is not attributable to it, and deploy left the phase gate the same day (§1). |
| — | **VM remediation** | **paused — the VM is offline (Malcolm, 2026-11-05)** | Not before a hosted demo is wanted, at publication. Then: `scripts/backup.sh` first; `culprit env capture` and `culprit diff` against `.env.prod.example` before any hand edit; add only the missing keys and never regenerate an existing role's password; `IMAGE_REGISTRY=ghcr.io/josh-heath123/culprit`; log the VM into ghcr; deploy by hand (`workflow_dispatch`); verify with `alembic current`. |
| 31 | Probes | **complete** | **Signed off 2026-11-03** (architecture session): merged via PR #19 (`a3f110a`), CI green on every job after two ambient dependency fixes (`335aa3b`, `96ac919`). Criteria 3 and 4 met; 1 and 2 carried into 31.1. History — as of 2026-09-12: built and locally green; CI not run. Criteria 3 and 4 PASS; 1 and 2 only partly demonstrable without the demo stack. One enforced invariant was deliberately changed (the binary-wide `net/http` ban, replaced by a per-package one) and one role was widened (`anomaly-detector` SELECT on `connections`) — both argued in §5 and both wanting a human eye. Q12 answered: both surfaces exist. (Carried from the retired Q12: Phase 30 field 4 asked capture for DNS resolvability, TLS certificate expiry and reachable ports, and built them as passive CONFIGURED facts — `component:X dns_resolves` and the like — that stop at a handshake, reading field 17 as "no application requests". Phase 31's own field list names `probe.net.dns_resolve`, `probe.net.tcp_connect` and `probe.net.tls_validity`. **Phase 31 must either re-site them as probes or state that both exist and why.**) **Review 2026-11-03:** every open item decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31. To complete: the human commits, then `/ci` green on the merge result, then merge. |
| 31.1 | Close the probe loop | **complete** | **Signed off 2026-11-04** (architecture session): PR #20 (`4f69ab3`), CI green on the merge result (run 41789133416). Criteria 2 and 4 refined and the auditor's risks decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31.1. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.1, all 17 fields. Phase 31 is merged; the branch `phase-31.1-probe-loop` is cut from `origin/main` = `a3f110a`, with the sign-off as its first commit. Order within the phase: the two gate repairs first — the boundary allowlist (it must exist before anything else lands under `cli/internal/`) and the emptied `.trivyignore` — then expectations, then data sources, then the demo-stack criteria. Replace the whole of §5 with this run's report. Do not stage `shared/uv.lock`. |
| 31.2 | Present what works | **complete** | **Signed off 2026-11-04** (architecture session): PR #21 green on every job; the review's five corrections and the lockfile change verified on disk in `a18c73e`, with the self-check's numbers evidenced in §5. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. **Go-ahead 2026-11-04:** the branch `phase-31.2-present-what-works` exists, cut from `origin/main` = `4f69ab3`. Read Phase 31.2 in the plan including "Carried in from Phase 31.1". **Review 2026-11-04 (before CI):** justfile fix ratified with one change (types generated from the lockfile, as CI does); criterion 4 refined; five README and LIMITS corrections to make on this branch before merge — `DIAGNOSTIC_PLAN.md`, end of Phase 31.2. The last-admin guard is Phase 32's third item. |
| 32, part 1 | The isolation walk | **complete** | **Signed off 2026-11-04** (architecture session): PR #22 (`972f288`), CI green on the merge result with the fault library 6/6 on Linux (run 41815764073). Criteria 1 and 3 refined; decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — all 17 fields, read with "How Phase 32 is run" at the end of the section, which wins where they differ. This run is **part 1 only: the walk, in the binary** — no migration, no API, no frontend, no worker change; those are part 2. Order: the two carried-in items first (CONFIGURED values rendered as shapes; the generated catalogue mirror), then the shared Investigation model and its conformance fixture, then `internal/isolate` and `culprit diagnose`, then the fault library and its CI job. Branch `phase-32-isolation-walk`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32, part 2 | The investigation in the control plane | **complete** | **Signed off 2026-11-04** (architecture session), subject to the quickstart verification on `main` recorded in §5. Merged via PR #23 (`a22da56`). Decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — "How Phase 32 is run", then "Part 2 — the investigation in the control plane" at the end of the section, which holds the work order, the criteria and what not to build. Branch `phase-32-control-plane`. Order: the carried-in items first (the token grant, the symptom's attestation, untested versus unexplored branches; then the last admin), then storage, the API, the view, the correlation engine's removal, and the quickstart, README and LIMITS last. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.1, part 1 | The system, on the Investigation screens | **complete** (PR #24 merged, run 41875987970 green) | **Reviewed 2026-11-04** (architecture session); look approved by Malcolm on the screenshots. PR #24 (`bd29351`). Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. |
| 32.1, part 2 | Everywhere else | **complete** (PR #25 merged, `072fb4f`) | **Signed off 2026-11-05** (architecture session), subject to the final run on `e97189f` being recorded green — 32.2's first step. Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. History: 2026-11-04: `2a851ee`, PR #25; run 41916090503 red on `e2e` only (quickstart bootstrap, Linux bind-mount ownership), fixed in the justfile, awaiting commit and CI. SARIF upload accepted (`self-check` green). Screenshots of every route were committed for review and removed from the tree in Phase 32.2 (they remain in history at `072fb4f`). **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32.1 — "Malcolm's review of the screenshots" and "Part 2 — everywhere else" at the end of the section, which hold the four review changes, the work order, the criteria and what not to build; field 14 as refined applies. Requirements: `docs/PRODUCTISATION.md` §2, §4, §7 and §8. First confirm with `gh` that PR #24 is merged with CI green; if not, stop. Follow the work order: the review changes first, the fresh-eyes review last. Branch `phase-32.1-part-2`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.2 | Close-out | **complete**, **signed off 2026-11-05** (architecture session) — `2e05980`, `2e187fc` on `main`; run 42083753833 green, `deploy` skipped; Images run 42084489435 green (§5) | **Brief (2026-11-05):** `DIAGNOSTIC_PLAN.md` Phase 32.2 — its work order, criteria and what not to do. Two commits: line endings alone first (message `..\phase-32.2-1-line-endings.txt`; stage it and stop for the human to commit), then everything else (`..\phase-32.2-2-close-out.txt`). Record PR #25's final run first. Branch `phase-32.2-close-out`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 33, part 1 | The agent, standing alone | **complete** (PR #27 merged, `57541e3`) | **Signed off 2026-11-06** (architecture session): every criterion executed by the tests and by `phase-auditor` on the real binary; the image check's Linux-only failure found by the audit and fixed before merge. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`. |
| 33, part 2 | The agent meets the control plane | **complete** (PR #28 merged, `58e7593`) | **Signed off 2026-11-10** (architecture session): every check on the pull request green, code scanning included after Q18; the CI-only criteria 8–10 verified to run and unable to skip. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`. |
| 33, part 3 | The operator's surface | **complete** (PR #31 merged, `e125b4b`) | **Signed off 2026-11-10** (architecture session): every pull-request check green; the Kubernetes recipe Ready in CI's kind cluster; every "cannot" in `SECURITY.md` held to a test by CI. Q19 ruled. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`. |
| 34, part 1 | The loop, in the binary | **complete** (PR #32 merged, `2ef3da6`) | **Signed off 2026-11-10** (architecture session): every check green; one conformance fixture read by Go and Python; the fault library 11/11 in CI. Q20 and Q21 ruled; criterion 3 refined. Decisions at the end of Phase 34 in `DIAGNOSTIC_PLAN.md`. |
| 34, part 2 | Outcomes in the control plane | **complete** (PR #33 merged, `0effc53`) | **Signed off 2026-11-11** (architecture session): every check green; the wrong-fix and right-fix loop asserted through a real agent in CI; the e2e race fixed by waiting, not loosening. Decisions at the end of Phase 34 in `DIAGNOSTIC_PLAN.md`. |
| 35, part 1 | The agent surface | **complete** (PR #34 merged, `60d2c92`) | **Signed off 2026-11-11** (architecture session): every criterion run in CI — the MCP loop through the real binary on Linux in the fault-library job, unfilterable; `e2e` did not run on the pull request (ambient, Q24), so part 2's step 0 confirms `main`'s push run green. Q22–Q24 ruled. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| 35, part 2 | The narrator | **complete** (PR #35 merged, `ac0a939`; its last commits through PR #36) | **Signed off 2026-11-11** (architecture session): every check on the pull request and on `main`'s push run green, read from GitHub; step 0 met. Parity's widening (`8a09d7e`) is honest; Phase 36 part 2 narrows it. Merged before the run finished, so the re-audit's fixes (`ec05453`) and the run report (`356012e`) landed with the close-out. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| 35, close-out | Land the re-audit's fixes; the review's corrections | **complete** (PR #36 merged, `08f7d65`) | **Signed off 2026-11-12** (architecture session): `main`'s push run 43167772415 green on every job; criteria 1–5 executed, each shown red before the change. Q25 ruled: item 4 and criterion 6 are withdrawn, because the brief rested on a wrong LIMITS sentence. The first run under the draft pull request rule, and it held. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| 36, part 1 | Budgets and the measurement | **complete when `main`'s push run on `716205f` is green** (PR #37 merged) | **Signed off 2026-11-12** (architecture session): every check on the pull request green, read from GitHub. The phase-auditor recomputed every rank with exact fractions and fuzzed Go against Python on 40,000 inputs; its two NOT MET findings were fixed and counted at the server. Three corrections are carried into part 2. Decisions at the end of Phase 36 in `PERFORMANCE_PLAN.md`. |
| 36, part 2 | The walk sees slow | **complete** (PR #38 merged, `d785af4`; `main`'s push run 43250669431 green) | **Signed off 2026-11-12** (architecture session): every check on the pull request was green, read from GitHub. The library's latency fault roots at inventory-service and verifies; a wrong fix gives `not_resolved`; without budgets it is `inconclusive`. Q21 is closed. Q26 is ruled, and Q27 corrected its premise. Decisions are at the end of Phase 36 in `PERFORMANCE_PLAN.md`. |
| 37, part 1 | Reading the database safely | **complete** (PR #39 `b3ef508`, close-out PR #40 `ee3e19e`) | **Signed off 2026-11-12** (architecture session): a read-only session refused at the server in CI; the demo's database is seeded; index facts are found both ways. Q27 ruled package isolation, built in the close-out. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 1 close-out | Package isolation; one schema for both manifest readers | **complete** (PR #40 merged, `ee3e19e`) | **Signed off 2026-11-12** (architecture session): every check on the pull request was green, read from GitHub. The audit's two attacks no longer type-check; each boundary package has one non-test file. The CodeQL alert was answered by redesign. Q28 is ruled (strict typing and a differential corpus, in part 2); Q29 is ruled. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 2 | Statements and plans | **complete when `main`'s push run on `1b2496b` is green** (PR #41 merged) | **Signed off 2026-11-13** (architecture session): every check on the pull request was green, read from GitHub. The generic plan comes from a prepared statement under `force_generic_plan` (the brief was wrong). `(category, sku)` brings the statement within budget, which `category` alone does not. Q28's corpus holds 5,684 manifests. Q31 and Q32 are ruled. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 3 | The database in the walk | not started | **Brief (2026-11-13):** `docs/PERFORMANCE_PLAN.md` Phase 37, "Part 3" at the end of the section: its decisions, work order, criteria and what not to build. Step 0: `main`'s push run on `1b2496b` green. Branch `phase-37-walk` from `origin/main` = `1b2496b`; its first commit is the part 2 sign-off. Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 38 | Bounds: what the browser downloads, and what a list returns | not started | `docs/PERFORMANCE_PLAN.md` Phase 38. "How Phase 38 is run" is written at the review before it. |
| 39 | N+1, where it can be seen cleanly | not started | `docs/PERFORMANCE_PLAN.md` Phase 39. "How Phase 39 is run" is written at the review before it. |

**Standing task, not a phase — new advisories should be found on `main`, not
mid-phase.** *(Folded into Phase 32.2, 2026-11-05.)* Three times now — OpenSSL in September, then PyJWT, certifi and
urllib3, then aiohttp, Pillow, filelock, pyasn1 and the Caddy build, both on
2026-11-03 — advisories published against pinned dependencies while a phase
sat waiting blocked that phase's CI. Add a weekly `schedule:` trigger that runs
the build-and-scan job on `main` (the image push and `deploy` steps already
require `github.event_name == 'push'`, so a scheduled run cannot publish or
deploy). A red scheduled run is then fixed in its own small pull request.
Dependabot security updates, a repository setting Malcolm can turn on, would
open those pull requests by themselves. Its own commit, not folded into a phase.

**Standing task, not a phase — `CLAUDE.md` size budget.** *(Folded into Phase 32.2, 2026-11-05.)* It is 37.2 KB
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

Claude Code overwrites this section at the end of every `/next`. Earlier
reports are in `git log -p docs/HANDOFF.md`.

```
Phase:        37, part 2 — statements and plans
Branch:       phase-37-statements, from origin/main = ee3e19e; 60184f9 the
              close-out sign-off, f1cff6f the phase, 74ab042 the audits'
              and CI's findings, then this report. PR #41.
Run:          2026-11-12 to 2026-11-13, /next, resumed after a context
              clear; the architecture session's rulings of 2026-11-13
              applied.
Status:       AWAITING DECISION (Q31). Built; CI green on 74ab042 (run
              43380877940), every PR check pass, no open alert. Q30's
              change is not built: as ruled it would catch
              probe.edge.impedance (Q31). Q32 is open and blocks nothing.

STEP 0
  main's push run 43293248631 on ee3e19e: 21 jobs success, deploy
  skipped.

RULINGS OF 2026-11-13 (architecture session) — RULED
  1 Q30 ratified with one change: key the fail-fixture exemption on the
    manifest (an empty expected_from), not the probe's name; a test holds
    every such probe to never returning fail, shown red; the exemption by
    name for probe.db.plan removed.
    NOT BUILT — Q31. probe.edge.impedance (Phase 31) also declares an
    empty expected_from, returns fail at 3 standard deviations and has a
    fail fixture, so the test as ruled is red on it. Malcolm chose to
    escalate (2026-11-13). The exemption by name stays; probe_test.go
    says why.
  2 The three places the brief did not match real Postgres — accepted:
    - Generic plans: a prepared statement explained under plan_cache_mode
      = force_generic_plan, on the extended protocol, nothing executed.
      The three tests are TestTheGenericPlanAgainstARealPostgres (new, in
      CI's Docker step, Postgres 16): the session read-only before,
      between and after every message (SHOW transaction_read_only on the
      same session); ANALYZE never sent; a second statement appended to
      the text refused by the server's Parse (42601), sendPlan's own guard
      bypassed. Red when sendPlan sends EXPLAIN (ANALYZE ...): "ANALYZE
      was sent". Its other check, that the statement's calls do not move,
      did NOT catch that mutation (pg_stat_statements does not count an
      EXECUTE inside EXPLAIN by default); the sent-text check holds it.
    - The demo plan walks ix_products_sku and filters category; the test
      asserts the filter on category.
    - (category, sku) brings the query within budget; category alone does
      not. Measured (the test's MEASURED lines; local, 2026-11-13; mean
      per call against the 20 ms budget):
        no index on category        153 ms   (159 ms in an earlier run)
        index on category alone     153 ms   (171 ms), verdict fail
        index on (category, sku)    0.025 ms, verdict pass
      CI, run 43380877940 (Linux): 96.1 ms, 96.4 ms (fail), 0.014 ms.
      Noted for part 3.
  3 Full suites not rerun locally; CI is the gate of record. Local runs
    were one package or one test at a time, no quickstart running.

WHAT WAS BUILT (f1cff6f; the work order)
  1 Q28: strict typing in both manifest readers — one type per field,
    null and empty refused naming the field, untyped values keep their
    text, unknown keys refused at every level. Go: typed.go walks yaml.v3
    nodes against a schema derived from Manifest; API: YAML12Loader ports
    yaml.v3's resolver and _typed builds plain data against a schema from
    the pydantic models. shared/tests/manifest_schema.json (61 fields)
    and manifest_corpus.json (5,684 cases: every field x 91 scalar forms,
    48 structural variants, the close-out audit's 85 manifests). Then
    query_mean_ms_max in both readers and the API's model.
  2 Q29: four statistics templates, filtered to this database's dbid and
    away from Culprit's role; text leaves the server only for SELECT,
    WITH, INSERT, UPDATE, DELETE, MERGE. plannedStatement, made only by
    planFromRow; sendPlan as in ruling 2.
  3 probe.db.statement_budget (integer rule in Go and Python, shared
    statement_conformance.json) and probe.db.plan (evidence, no
    expectation; filter columns by name only; before 16 inconclusive).
    culprit mcp refuses probe.db.plan, any queryid and any input to the
    statement probe, before anything is sent.
  4 Readings re-judged in Go, Python and POST /readings.
  5 The demo's 20 ms query_mean_ms_max on
    schema:inventory-db/public.products.
  6 PROBES, PERMISSIONS, LIMITS.

FIXED AFTER THE AUDITS AND CI (74ab042)
  - CI run 43376316313: test_probes_api counted fourteen probes. Sixteen;
    the exact set is still held to the Go source.
  - Four new `# type: ignore` in api/app/model/manifest.py (§6 counts an
    ignore as a weakening) replaced by annotations and isinstance;
    pyright 0 errors.
  - A4: the CREATE ROLE ... PASSWORD statements ran before the window, so
    their check could not fail. They now run inside each window, in this
    database and another, and the test requires the reading to list them
    as "text not kept".
  - The MCP refusal count could not move (no budget declared, so the
    probe returned before its source). It can now: 5 calls counted with
    the guard removed.
  - probeStats's version and extension gates and unloaded() had no test:
    gates_test.go, red when either gate is changed.
  - probe.db.plan read `culprit probe --input queryid=7` (an int) as
    unnamed. An exact int is taken; a float is refused ("pass it as
    text").
  - Found running the demo test: twenty slower statements no budget
    applies to pushed the judged one out of the 20 kept, and a window
    within budget read inconclusive. Statements a budget applies to are
    now kept before the rest;
    TestStatementsWithABudgetAreKeptBeforeThoseWithout, red without it.
  - A statement too large to judge is named in the reason.
  - Stale GENERIC_PLAN comments corrected; README says sixteen probes.

CRITERIA (phase-auditor on f1cff6f, re-checked after 74ab042)
  1 Nothing outside the templates reaches the database — MET (unit,
    counted; mutations red); real server in CI.
  2 The statement rule's fixture in Go and Python, five cases, red when
    the comparison moves — MET.
  3 On the demo's database: over budget without an index; the plan reads
    products filtering category (sku index, ruling 2); within budget with
    (category, sku) — MET locally and in CI.
  4 A secret-looking constant leaves no trace — MET (unit; real server in
    CI).
  5 Without db.plan.read the plan probe refused and a table budget
    unjudged, saying so; without pg_stat_statements both inconclusive;
    before 16 the plan probe inconclusive — MET, the gates now tested at
    the session too.
  6 culprit mcp refuses, counted — MET; the count can now go red.
  7 A disagreeing statement reading refused by Go, Python and the API —
    MET (Go and Python mutated red; the API in CI).
  8 Every PR check green — see CI.
  A1 The corpus agrees — MET (5,684 cases, both readers).
  A2 The auditor's 23 splits in the corpus — MET BY INSPECTION: the 85
     seeds are there, and every split LIMITS@ee3e19e names is a seed with
     its expected outcome; the test checks only the count. Not labelled.
  A3 Loosening either reader turns it red — MET (Go 1024 cases; API 1048
     and 48).
  A4 CREATE ROLE ... PASSWORD in no reading while the products text is
     kept — MET IN SUBSTANCE, NOT AS WRITTEN: the statements run inside
     the window on the demo's database and on a Postgres 16 test
     database, written as Culprit's migrations write them, not through
     the quickstart's Alembic migrations, which need the control plane's
     TimescaleDB image. For the review to reword, or to ask for the
     quickstart itself.
  A5 Another database's statement not read — MET (dbid pinned in unit;
     both Docker tests in CI).

DELIBERATELY NOT BUILT
  No walk change, no statement_budget_exceeded or missing_index, no fault
  case, no traffic by Culprit, no reset, no EXPLAIN ANALYZE, no row read,
  no index created by Culprit (phase-auditor: none found).

CI
  f1cff6f  run 43376316313  failure on test only (the probe count, above);
           every other job success.
  74ab042  run 43380877940  https://github.com/Josh-Heath123/Culprit/
           actions/runs/43380877940 — attempt 1: e2e (none) failed before
           its first step, "The hosted runner lost communication with the
           server" (runner fault; narration-parity skipped behind it);
           rerun of the failed job, attempt 2: every job success; build /
           publish and deploy skipped.
    PR checks: every one pass or skipping — CodeQL, Analyze (go, python,
           javascript-typescript, actions), Culprit included.
    Code-scanning alerts open: none (pr=41, refs/pull/41/merge,
           refs/pull/41/head all empty).
    The branch contains origin/main = ee3e19e, so the branch is the
    merge result.

AUDITS
  invariant-auditor (f1cff6f): CLEAN. Risks: the plan mechanism differs
    from the plan's text (ruled, 2); a stale comment (fixed); the four
    ignores (fixed); tables outside `public` taken as public (in LIMITS);
    the statistics session's timeout is its own 20 s plus the window, not
    the CLI's --timeout (left; for the review).
  phase-auditor (f1cff6f): NOT COMPLETE then — A4 could not fail, the MCP
    count and A2 could not fail, the gates untested, the int queryid, the
    too-large pass. All fixed in 74ab042 except A2's labels (above) and
    SELECT ... INTO on PostgreSQL 14–15 (Q32, unverified).

LEFT OPEN
  Q31 (blocks Q30's change only): impedance and the manifest-keyed
    exemption.
  Q32 (blocks nothing): SELECT ... INTO before PostgreSQL 16.
  For the review: A4's wording, A2's labels, the statistics session's
    timeout.
  Housekeeping: the phase-auditor left files under /tmp (*.bak,
    /tmp/audit37/); its cleanup was refused.
```

---

## §6. Escalate to the architecture session when

Do not guess on any of these. Stop, add the question to §3 marked as blocking,
explain it in §5's run report, and stop.

- The plan's stated interface, data model or acceptance criterion turns out to be
  wrong or under-specified against the real code.
- Implementing a phase appears to require something on its own field-17 list.
- A gate can only be made green by weakening it — widening a `lint-imports`
  contract, adding a `# type: ignore`, skipping a test, widening a Postgres role.
- A decision of record would have to be reversed — `docs/DIAGNOSTIC_PLAN.md` §1
  (D1–D8), or one recorded in an earlier run report.
- Two intent sources disagree in a way the plan does not describe how to rank.
- Presenting, describing, screenshotting or recording the product would mean
  showing something that does not exist or does not work
  (`docs/PRODUCTISATION.md`, standard 3).
