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
| Plan of record | `docs/DELIVERY_PLAN.md` (Phases 40–43), from 2026-11-18. `docs/PERFORMANCE_PLAN.md` (Phases 36–39) and `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) are complete; D1–D8, the standing invariants and P1–P8 still bind. |
| Current phase | **40, part 1 — the new identity: the dashboard** — `not started`. Brief: `docs/DELIVERY_PLAN.md` §2 (I1–I7) and Phase 40, "Part 1 — the dashboard", with C1 (carried from Phase 39) first. Step 0: `main`'s push run 44327031951 on `33df658`. |
| Previous phase | **39, part 2 — the walk and the fault — merged as `33df658` (PR #48) and signed off 2026-11-18.** Run 44321940704 on `a832381`, the report's run 44326796071 and `main`'s push run 44327031951 on `33df658` green on every job, read from GitHub. Q38–Q40 ruled and carried out; two mutations of the join shown red by the architecture session; the run's seven decisions accepted, the first amended by C1. Recorded at the end of Phase 39 in `PERFORMANCE_PLAN.md`, which is complete. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-40-identity`, to be cut from `origin/main` = `33df658`. Its first commit is the review: `git apply ../phase-39-2-review.patch`, then `git commit -F ../phase-39-2-review.txt` (`docs/DELIVERY_PLAN.md`, `docs/PERFORMANCE_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Then C1, as its own commit, pushed at once. Open a draft pull request and mark it ready when the run report is committed. Run the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. Do not commit the owner's reference image. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q38, Q39 and Q40 are recorded at the end of Phase 39 in `PERFORMANCE_PLAN.md`. | | |

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
| 37, part 3 | The database in the walk | **complete** (PR #42 `1d20322`, PR #43 `883e9b2`, PR #44 `4619099`) | **Signed off 2026-11-17** (architecture session): PR #44's last run 44072232611 green, read from GitHub; existing test faults unchanged; Q35's criteria met in CI over two runs; Q36 applied. Phase 37 is complete. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 38, part 1 | Bundles | **complete** (PR #45, `3d9fb33`) | **Signed off 2026-11-17** (architecture session): run 44088509299 green on every job, read from GitHub; the report's commit green on attempt 2 of 44091691574. Decisions accepted; Q37 ruled. Recorded at the end of Phase 38 in `PERFORMANCE_PLAN.md`. |
| 38, part 2 | Lists | **complete** (PR #46, `02bae0d`) | **Signed off 2026-11-17** (architecture session): run 44167165860 green on every job on attempt 1, read from GitHub; the criteria checked on disk in place of the audits the run did not reach. The demo's count of 0 is accepted and carried to Phase 39 part 2. Phase 38 is complete. Recorded at the end of Phase 38 in `PERFORMANCE_PLAN.md`. |
| 39, part 1 | The measurement | **complete** (PR #47, `6b0de5d`) | **Signed off 2026-11-18** (architecture session): the report's commit green on every job (run 44189651276), read from GitHub; the real-Postgres tests rerun, and two mutations shown red; the run's three decisions accepted. Recorded at the end of Phase 39 in `PERFORMANCE_PLAN.md`. |
| 39, part 2 | The walk and the fault | **complete** (PR #48, `33df658`) | **Signed off 2026-11-18** (architecture session): runs 44321940704, 44326796071 (the report) and 44327031951 (`main`'s push) green on every job, read from GitHub; Q38–Q40 ruled and carried out; the walk's and `verify`'s tests rerun and two mutations of the join shown red; the run's seven decisions accepted, the first amended by C1. Phase 39 is complete, and with it `PERFORMANCE_PLAN.md`. Recorded at the end of Phase 39 there. |
| 40, part 1 | The new identity: the dashboard | not started | **Brief (2026-11-18):** `docs/DELIVERY_PLAN.md` §2 (the identity, I1–I7) and Phase 40, "Part 1 — the dashboard": C1, the N+1 route's page carried from Phase 39, first, as its own commit pushed at once; then the work order from item 0, the assessment, written into the report before any screen changes; its criteria and what not to do. Step 0: `main`'s push run 44327031951 on `33df658`. Branch `phase-40-identity` from `origin/main` = `33df658`; its first commit is the review (`../phase-39-2-review.patch`, message `../phase-39-2-review.txt`). Open a draft pull request and mark it ready when the run report is committed. The report shows every screen at 1280 px and one at 375 px. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        39, part 2 — the walk and the fault: n_plus_one, the demo's
              relation and route, the library's two N+1 cases
Branch:       phase-39-walk, from origin/main = 6b0de5d. 6349f84 the
              review; items 1-6 (72df2ef, 74e01a7, eb23f87, 000c4a5,
              c460697, with 8d11f70, d3ee1d5); the page and budget from CI
              (1686be8, c58cc54); the invariant audit (fc0a9c2); Q38
              (0ed3f4a), Q39 (d923726), Q40 (a832381); the earlier reports
              (ae091f9, b958d2e, 07de8e6); then this report with the
              README's N+1 case. PR #48.
Run:          2026-11-18, /next, then Q38-Q40 as ruled. Local gates one at a
              time, in the foreground. The fault library never run locally.
Status:       COMPLETE pending review. CI green on a832381 (run
              44321940704, every job and every PR check; no open alert).
              Nothing blocking. One thing first for the review (below).

FIRST FOR THE REVIEW — THE FASTEST RUNNER YET, UNDER THE NEW BUDGET
  Run 44321940704, the first at 20 ms, landed on a faster runner than any
  before: the fault's sample 45 was 22.6 (n-plus-one) and 23.5 ms
  (n-plus-one-shared), 2.6 and 3.5 ms over the budget; the fix's slowest
  6.5 ms. Q40 reasoned from 27.7 ms (about 7 ms of headroom). Q40's stop
  line for step 1 (sample 45 at 24 ms or less: Q41) applied to run
  44313908008, whose lowest was 57.6 ms, so this run does not stop the
  phase; but the same line on this run would have. The budget is
  unchanged; LIMITS and the budget's why now give the true range (22.6 to
  62.9 ms) and headroom (2.6 ms, a runner about a tenth faster could
  flake).

Q40 — RULED (architecture session, 2026-11-18), recorded for the plan
  On the fastest runner seen (44307212906 attempt 2) the fault's sample 45
  was 27.7 ms and the fix's slowest 13.1 ms, a ratio of 2.11; amended
  decision 4's margins need 2.25, so no budget at a page of 200 meets
  both. Ruling: (1) add run 44313908008 to the table; stop as Q41 if any
  fixed slowest >= 16 ms or fault sample 45 <= 24 ms; otherwise (2) the
  details route's latency_p95_ms is 20, the page 200, the why the spread
  and the ruling; (3) on the details route only, remove the harness's
  p95-factor checks on both sides: the check is the judge's verdict at
  the budget (measureLatency), with the walk's root, verify's verdict and
  results.json, every reading still logged; (4) commit the two N+1
  results.json entries exactly as 44313908008 wrote them, then just
  accuracy-readme; (5) LIMITS: the ruling, and an N+1's cost is the
  runner's round trip; (6) every existing case keeps its result. Q40 is
  deleted from §3.

EARLIER RULINGS IN THIS RUN (recorded in the reports of ae091f9, b958d2e
and 07de8e6, and in git log -p docs/HANDOFF.md)
  Q38: decision 4 restated in the judge's terms (fixed slowest <= 2/3 of
    the budget, fault sample 45 >= 1.5x, over two runs); the database
    settled after 0004 and postgres's health check quiet. It did not move
    the slow answers.
  Q39: the slow answers were the demo's own process (cold first request,
    Python 3.12's first full collection, the first console metrics
    export). The demo warms its read paths, collects and freezes its
    startup heap (shared/startup.py) and exports metrics hourly in the
    faults stack. The fix's slowest fell from 28-117 ms to at most 13.1.

THE TABLE (GET /products/details, page 200, in the judge's terms)
                                   fault: sample 45     fix: slowest
  before Q39 (5 runs)              44.1 to 62.9         28.1 to 117.1
  44307212906 attempt 1 (15 ms)    46.3, 46.1           5.5
  44307212906 attempt 2 (15 ms)    27.7, 30.2           13.1
  44313908008 (15 ms)              57.6, 58.0           6.0
  44321940704 (20 ms)              22.6, 23.5           6.5
  Q40's step 1 on 44313908008: slowest 6.0 < 16, sample 45 57.6 > 24: no
  Q41.

DECISIONS OF THIS RUN (for the review)
  1. The page and the route's list bound are 200 (GET /products' cap);
     at 50 the N+1 measured about 16 ms.
  2. The root is the route; reproduced is asked of the latency reading
     that found it slow (the per-item reading is evidence and passes
     either way). The tree repeats the route as symptom and root.
  3. The not-isolated sentence says "this walk does not run in an
     environment declared isolated", because the agent never sets
     Isolated whatever culprit.yaml declares.
  4. An unexplored N+1 (no statement seen, inconclusive, refused) is a
     partial, as every unexplored database hypothesis is.
  5. The database fault's fix leaves the tree at 0001-0003 and the
     database at 0003; every case starts at 0004 (atTop, then settled).
  6. inventory-service's warm-up skips and logs a read that fails (at
     the missing-index fault's 0002 there is no product_details).
  7. One unpushed commit was re-authored with the GitHub noreply address,
     set for this repository only, after GitHub refused the push (GH007)
     and the human chose it; nothing pushed was rewritten.

ITEMS
  1 demo: 0004 product_details (one row per product, additive);
    GET /products/details, a join or, with N_PLUS_ONE_FAULT, one
    statement per product; budgets: latency_p95_ms 20, response_items_max
    200 at /products; faults-inventory-isolated (isolated: true). Since
    Q39: shared/startup.py, the warm-up, gc.freeze, hourly metrics.
  2 n_plus_one ("One statement per item") in Go, Python, the frontend and
    investigation_conformance.json; the probe discriminates it;
    catalogue.json regenerated.
  3 the walk: isolate/per_item.go, asked at the database pass's condition
    and, isolated, before it; supported / ruled out / unexplored as
    decision 7; the recommendation; the not-isolated sentence.
  4 the library: n-plus-one (isolated, load generator stopped through
    verify) and n-plus-one-shared, shard 2; every latency reading logged
    in the judge's terms; results.json from run 44313908008.
  5 verify: the description says whether the cited statement still runs
    per item; a rerun with no statement is not measured; another per-item
    statement is named. Verdict rules untouched.
  6 documents: PROBES, LIMITS (N+1 in the walk; the slowest answer; a
    just-restarted service; the round trip), and the README's N+1 case,
    from run 44321940704's log; the accuracy number 9 of 9, rendered by
    just accuracy-readme from results.json.

CRITERIA
  Isolated: root n_plus_one on the route, statement and counts named,
    recommendation given                                  PASS (CI)
  With the fix: within budget, verify verified, the
    description says the statement no longer runs per item PASS (CI,
    44313908008 and 44321940704)
  Not declared isolated: no n_plus_one root, the line     PASS (CI, test)
  The list probe counts the new route's page              PASS (items:200)
  The join: every outcome by a walk test; the
    no-statement -> ruled_out mutation red                PASS
  n_plus_one: Go, Python, frontend agree                  PASS
  0004 round-trips                                        PASS (local
    Docker; CI migration-round-trip)
  The budget's margins from >= 2 CI runs                  PASS as Q40
    ruled (the table)
  Unchanged elsewhere: every existing case's root and
    verdict (shard 1 and missing-index green in every run
    since); goldens; the demo's expected findings        PASS. Listed:
    the missing-index statement ends with the not-isolated sentence;
    its trees drop 0004 with 0003
  CI green on the merge result                            PASS
  LLM_PROVIDER=none changes nothing                       PASS (e2e (none))
  Report committed before the PR is marked ready          PASS

NOT BUILT (as the brief says)
  No N+1 outside an isolated environment; no change to the probe's
  measurement or verdicts; no statement budget from the bracket; no new
  template, capability or role; verify's verdict rules unchanged; no ORM
  source, no traces; no warm-up request in probe.http.latency (Q39: a
  plan decision).

AUDITS
  invariant-auditor (6349f84..fc0a9c2): NOT CLEAN on V1 (two test
    subjects formatted), with R1 and R2 in verify's note; all fixed in
    fc0a9c2. Not re-run on the later commits (harness, demo startup,
    compose, docs).
  phase-auditor (6349f84..8e5b746): every criterion MET but verify
    verified and CI green, both since met; its other items (the why, the
    report, the README's N+1 case, the accuracy claim) done.

LOCAL GATES (Windows, one at a time, in the foreground)
  just lint (after every change), typecheck, lint-imports,
  check-schema-drift, check-no-llm-imports, check-invariants,
  check-scan-coverage, check_coupled_files: clean. go test -p 2 ./...:
  every package ok. api 1,778, shared 686, worker 93, mcp_server 21,
  extractors/python 19 (migrations), node 22, frontend 19. Docker:
  TestTheDemoDatabase. The demo services' startup with TestClient. Not
  run locally: the fault library (instructed), e2e, the frontend build.

CI (PR #48)
  Runs 44263168879 to 44313908008: as in the earlier reports (the page
    50, the budget, Q38, Q39, the results check).
  44321940704 on a832381: success on every job (deploy and publish
    skipped); fault-library (1) and (2) green; all 25 PR checks pass or
    skipping; no open code-scanning alert (pr=48, refs/pull/48/merge,
    refs/pull/48/head). main had not moved (6b0de5d): the merge result.
  This report's own commit runs on the pull request after it.
```

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
