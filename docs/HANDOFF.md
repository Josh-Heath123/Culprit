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
| Current phase | **40, part 2 — the new identity: the repository** — `not started`. Brief: `docs/DELIVERY_PLAN.md` §3 (S1–S4) and Phase 40, "Part 2 — the repository", with the review of part 1 and part 2's brief beneath it: C2 (the focus ring) first. Step 0: `main`'s push run 44375710199 on `624c6e3`. |
| Previous phase | **40, part 1 — the new identity: the dashboard — merged as `624c6e3` (PR #49) and signed off 2026-11-18.** Runs 44340916627 on `1f3080a` and 44346373804 on the report, `b234e12`, green on every job, read from GitHub. C1 met over two runs. Three mutations shown red by the architecture session; the run's five decisions accepted, the third amended by C2. Recorded in `DELIVERY_PLAN.md`, Phase 40, "Review of part 1". |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-40-repository`, to be cut from `origin/main` = `624c6e3`. Its first commit is the review: `git apply ../phase-40-1-review.patch`, then `git commit -F ../phase-40-1-review.txt` (`docs/DELIVERY_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Then C2, as its own commit. Open a draft pull request and mark it ready when the run report is committed. Run the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. Do not commit the owner's reference image. |
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
| 40, part 1 | The new identity: the dashboard | **complete** (PR #49, `624c6e3`) | **Signed off 2026-11-18** (architecture session): runs 44340916627 and 44346373804 (the report) green on every job, read from GitHub; C1 met over two runs; three mutations shown red; the run's five decisions accepted, the third amended by C2 (the focus ring). Recorded in `DELIVERY_PLAN.md`, Phase 40, "Review of part 1". |
| 40, part 2 | The new identity: the repository | not started | **Brief (2026-11-18):** `docs/DELIVERY_PLAN.md` §3 (S1–S4) and Phase 40, "Part 2 — the repository", with "Part 2 — brief" beneath the review of part 1: C2, the focus ring, first, as its own commit (with the review copies of the screenshots removed); then the hero, the captures, the diagram, the README, `docs/GUIDE.md` and `scripts/check_readme.py`, under its eight decisions; its criteria and what not to do. Step 0: `main`'s push run 44375710199 on `624c6e3`. Branch `phase-40-repository` from `origin/main` = `624c6e3`; its first commit is the review (`../phase-40-1-review.patch`, message `../phase-40-1-review.txt`). Open a draft pull request and mark it ready when the run report is committed; the report links the README as GitHub renders it on the branch. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        40, part 1 — the new identity: the dashboard (with C1, carried
              from Phase 39)
Branch:       phase-40-identity, from origin/main = 33df658. 1ad98c7 the
              review; 61a0546 C1; 329171d the assessment (item 0, before
              any screen changed); 8cba501 items 1-8; ded4f19 the audit's
              findings; 1f3080a the e2e fix; then this report with the
              README's N+1 case and the screenshots. PR #49.
Run:          2026-11-18, /next. Local gates one at a time, in the
              foreground. The fault library never run locally.
Status:       COMPLETE pending review. CI green on 1f3080a (run
              44340916627, every job; all 25 PR checks pass or skipping; no
              open code-scanning alert). main has not moved (33df658), so
              that is the merge result. Nothing blocking; no Q41.

FIRST FOR THE REVIEW — THE LOOK
  docs/screenshots/phase-40-review/ holds every screen at 1280 px and the
  investigation at 375 px, from run 44340916627's e2e artifact
  (e2e-screenshots-none), none touched by hand. Start with
  investigation-complete-1280.png, investigation-complete-375.png,
  investigations-1280.png and sign-in-1280.png. The folder is for this
  review; remove it when the look is approved (32.1 part 2 did the same).
  The README's four screenshots in docs/screenshots/ are from the same run.

C1 — THE DETAILS ROUTE'S PAGE 500, BUDGET 25 MS (61a0546)
  DETAILS_PAGE 500 (the default page and the ?limit= cap);
  response_items_max 500 at /products; latency_p95_ms 25. The whys and
  LIMITS give page 500 and the measured range; test_manifest_budgets.py
  pins 25 and 500; the library expects "ran 500 times for the 500 items".
  No harness check added back (Q40). Every existing case kept its root and
  verdict (both shards green in all three runs).
  The check, from the LATENCY lines (fault: sample 45 >= 37.5 ms; fix:
  slowest <= 16.7 ms, measured and in verify's runs):
                               fault: sample 45      fix: slowest
    44333504867 (61a0546)      144.3, 142.6          <= 12.3 (6.5, 7.0 measured)
    44336394900 (8cba501)      102.1, 98.5           <= 6.2  (6.2, 5.8 measured)
  MET in every reading of two runs. These runners were slower than the
  architecture session's projection (about 50 ms at 500): the fault's
  margin is wide; the fix's slowest stayed at the join's few ms.
  The README's N+1 case retaken from run 44333504867's log (the README
  OUTPUT block, copied by script; nothing typed): page 500, 25 ms,
  "ran 500 times for the 500 items", sample 45 at least 143.653 ms.

ITEM 0 — THE ASSESSMENT (committed in 329171d, before any screen changed)
  Routes and their jobs
    /login                    sign in to this control plane
    /investigations           every stored walk, newest first; an admin
                              can start one through an agent
    /investigations/:id       one walk: its diagnosis, verification,
                              narration, fault tree, symptom, hypotheses
    /incidents[/:id]          the retired correlation engine's record,
                              read-only (timeline, detail, Ctrl K palette)
    /postmortems[/new|/:id]   write, read and delete postmortems
    /settings/services        the system model (admin)
    /settings/users           accounts and roles (admin)
    /settings/agents          pairing and grants (admin)
    *                         not found; admins-only for a member
  The most important information on each screen
    investigation view   the root (or where the walk stopped) and its
                         statement; then the four checks; then the edges
    investigations       per row: the symptom and its root or stop
    login                the two fields and the one action
    settings             the list being managed, then the form
    incidents            that it is history; the timeline
    postmortems          titles and their embedding status
    not found            the path that was asked for, and the way back
  Inconsistencies found
    1 the answer was not the editorial moment (the h1 was the symptom);
    2 glass on data (the Symptom card) and on a form (sign-in);
    3 cantaloupe on the brand dot and an unused badge as well as the root;
    4 "complete" and "admin" in the brand tone of links and the button;
    5 three title sizes; 6 three field styles; 7 error text two ways
    (boxed, bare, and mono in services); 8 labels uppercase sans in some
    places, sentence case in others; 9 motion only colour, 150 ms, default
    easing; 10 Vite's favicon, a CSS dot for a mark.
  Data-heavy (dense, solid, quiet): the investigation view, the lists,
  settings, incidents, postmortems. Expressive (graticule; glow on
  sign-in only): sign-in, empty states, not found.

ITEMS 1-8 (8cba501, ded4f19, 1f3080a)
  1 Tokens. Surfaces are plum at other lightnesses (hue 270, saturation
    44%): a well #180e23, the page #221331, panels #261537 .. #392053;
    cream #fdfdfd, muted #cbc1d8, subtle #ab9dbd; violet fill and ring
    #7540f5, violet text #b69cff; --culprit #d6fa4a (was --highlight),
    plum on it; verdicts and severities re-derived (pass #3ddbae, fail and
    breaks #ff8070, inconclusive #6cc6ff, degrades #ffaa52, plum-greys);
    tints at 13% over plum, lines at 38%; a title and two display steps,
    a mono label tracking, the spacing step, radius and shadow steps, a
    culprit glow, 180 ms ease-out by default. test_design_tokens.py: the
    new sets; every boundary 3:1 on every surface; the ring 3:1 where
    controls sit; the anchors exactly; the surfaces plum by lightness
    alone; the hue-separation test (30 degrees from lime and violet, or a
    grey under 25% saturation).
  2 Restraint. check_frontend_tokens.py allows culprit utilities only in
    Diagnosis, FaultTree, InvestigationList (a row's root) and Brand (the
    mark), glass only in AppHeader, dialog and tooltip; a declared file
    that no longer uses its token fails.
  3 Components: violet primary, quiet secondary/outline/ghost, a press;
    one field style (a well inside a 3:1 boundary); no lime badge; Card
    solid only; a mono Label; ErrorNote and SuccessNote (21 failure
    paragraphs became ErrorNote); the graticule on empty states; glass
    dialogs, palette and tooltips; violet ring 2 px, offset.
  4 Screens. The investigation's h1 is its answer: the root in mono
    display under the lime "Root" marker, a lime rule beside the
    statement (the diagnosis line), the symptom a label above; a partial
    is "Walk stopped at" in the inconclusive tone, never lime. The fault
    tree's root node in the lime outline glow. Symptom card and sign-in
    solid. One title scale; labels in mono capitals; code and readings
    in wells.
  5 Motion: 150-220 ms ease-out on hover, press, the tree's edges and
    dialogs; nothing animates data.
  6 The mark: a measuring ring with four ticks and a lime centre, in
    Brand.tsx, frontend/public/favicon.svg (replacing Vite's),
    docs/brand/mark.svg and wordmark.svg.
  7 The screenshots retaken by e2e (above).
  8 PRODUCTISATION §2's status line.

DECISIONS OF THIS RUN (for the review)
  1 The answer's heading is the root subject (mono, display), with the
    statement beneath it as the diagnosis line, rather than the whole
    statement at display size: statements run to 300+ characters.
  2 Lime marks four places: the investigation's root and diagnosis line,
    the tree's root node, a list row's root, and the mark (the plan names
    the mark's dot).
  3 The ring is violet itself, as I2 says, so controls stay on the well,
    the page, a panel or glass, where it measures 3.0-3.4:1. Violet is
    2.3-2.8:1 on surface-2, surface-3 and the tints: no control sits there
    (LIMITS, new entry). The alternative was a lighter ring.
  4 The graticule is an SVG (two paths), because a pattern fill would
    need a colour prop the token gate refuses.
  5 A complete diagnosis with no remediation now says "The walk suggests
    no fix for this root." (before: nothing).

CRITERIA
  Every colour from a token; check-frontend-tokens and
    test_design_tokens pass, with the restrictions and the hue
    test; each mutation red                                   PASS
  Contrast: text 4.5:1 on every surface; boundaries and the
    ring 3:1                                                  PASS, the
    ring as decision 3 (after the audit's finding, ded4f19)
  Lime only where the answer is marked; glass only on
    layered components                                        PASS (gate)
  reducedMotion 'reduce': no transition (e2e)                 PASS (CI,
    "motion: 150 to 220 ms, and none under reduced motion")
  Nothing lost: every e2e assertion holds at four widths,
    every route, keyboard-only                                PASS (CI
    44340916627, e2e (none) and (stub)); the e2e diff only adds
  The report shows every screen at 1280 and one at 375        PASS (above)
  Do NOT: no functionality removed, no dependency (Inter 700
    is in the installed package), no light theme, no data
    animated, the reference image not committed               PASS
  C1 as above                                                 PASS

MUTATIONS SHOWN RED (each restored; the tree checked after)
  bg-culprit on the primary button     check: "culprit token outside the
                                       answer", button.tsx:17, exit 1
  bg-glass on Evidence                 check: "glass token outside a
                                       layered component", exit 1
  --degrades back to #f2d75b           hue test: degrades-culprit
  --inconclusive back to #b9a6ff       hue test: inconclusive-brand-fill,
                                       inconclusive-brand
  --line-strong #5a4c6a                3:1 test: 6 pairs
  --surface-1 one step lighter         ring test: ring-on-surface-1
  and five parametrised restriction mutations in the check's own tests.

AUDITS
  invariant-auditor (1ad98c7..8cba501): CLEAN. No gate weakened; C1
    touched only the route's page, budgets, pins, the library's expected
    text and LIMITS. Risks noted: the four decorative tokens are exempt
    from contrast; the 25 ms budget was a projection (now measured, C1).
  phase-auditor (1ad98c7..8cba501): NOT COMPLETE on one criterion — the
    ring under 3:1 on controls this phase placed on surface-2 (sign-in
    card, services connections box) and degrades-tint (the agent
    notice's link). Fixed in ded4f19: all three on a panel or a well;
    Card lost its surface-2 variant; RING_SURFACES says why. Its scope
    note (the graticule on admins-only, not named by I4) also taken. Not
    re-run after the fixes.

LOCAL GATES (Windows, one at a time, in the foreground)
  just lint, typecheck, lint-imports, check-schema-drift,
  check-no-llm-imports, check-invariants, check-scan-coverage,
  check-frontend-tokens, check_coupled_files: clean. just test: api 1,840
  (6 skipped), worker 93, mcp_server 21, 39. Frontend: tsc -b, vite
  build, oxlint (three only-export-components warnings, as on main), node
  tests. Not run locally: the fault library (instructed), e2e.

CI (PR #49)
  44333504867 on 61a0546 (C1): success on every job.
  44336394900 on 8cba501: e2e (none) and (stub) red on one tour test —
    DiagnosisHeading was a <header>, so locator('header') found two;
    every other job green, fault library included (C1's second run).
  44338092108 on ded4f19: the same e2e failure, for the same reason.
  44340916627 on 1f3080a: success on every job (deploy, publish
    skipped); 25 PR checks pass or skipping; no open code-scanning alert
    on refs/pull/49/merge. main not moved: the merge result.
  This report's own commit runs on the pull request after it.

NOT BUILT (as the brief says)
  No light theme; no dependency; nothing removed; no data animated; the
  reference image not committed; the README rewrite, hero, captures and
  diagrams are part 2.
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
