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
(changed 2026-11-06, Joshua's decision). Claude Code commits its own work on
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
| Plan of record | `docs/FIELD_READINESS_PLAN.md` (Phase 44), from 2026-11-21: the audit and optimisation of the whole application before the first field trial. `docs/DELIVERY_PLAN.md` (40–43), `docs/PERFORMANCE_PLAN.md` (36–39) and `docs/DIAGNOSTIC_PLAN.md` (26–35) are complete; D1–D8, the standing invariants and P1–P8 still bind. |
| Current phase | **44, part 1 — the audit** — `awaiting decision`: the register is written (`docs/FIELD_READINESS_PLAN.md` §5, 92 findings, six S1), with the dashboard's rendering (4.7) not covered; the review rules on every finding and on the six questions in §5. Step 0 done: run 44881325932 attributed (a kind image import that left nothing on the node; F44-007) and green on attempt 2. Report in §5 below. |
| Previous phase | **Housekeeping, part 2: the last alerts — merged as `ddb275e` (PR #70) and signed off 2026-11-21.** Runs 44879138798 and 44880245200 (the report) green on every job, read from GitHub; #67, #68 and #69 closed as merged; alert #9 dismissed under Q45; every commit Verified. Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the housekeeping, part 2". |
| Deploy | **Paused, 2026-11-05 — Joshua's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-44-audit`, to be cut from `origin/main` = `ddb275e`. Its first commit is the review, signed: `git apply ../phase-44-brief.patch`, then `git commit -F ../phase-44-brief.txt` (`docs/FIELD_READINESS_PLAN.md`, new; `docs/DELIVERY_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Scratch work, screenshots and logs go to `../audit-44/`, never into the repository. Open a draft pull request and mark it ready when the run report is committed; if the run stops on a question, it stays a draft. Run `just lint` before every push and the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q45 is recorded at the end of Phase 43 in `DELIVERY_PLAN.md`, after Q42, Q43 and Q44. | | |

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
| — | **VM remediation** | **paused — the VM is offline (Joshua, 2026-11-05)** | Not before a hosted demo is wanted, at publication. Then: `scripts/backup.sh` first; `culprit env capture` and `culprit diff` against `.env.prod.example` before any hand edit; add only the missing keys and never regenerate an existing role's password; `IMAGE_REGISTRY=ghcr.io/josh-heath123/culprit`; log the VM into ghcr; deploy by hand (`workflow_dispatch`); verify with `alembic current`. |
| 31 | Probes | **complete** | **Signed off 2026-11-03** (architecture session): merged via PR #19 (`a3f110a`), CI green on every job after two ambient dependency fixes (`335aa3b`, `96ac919`). Criteria 3 and 4 met; 1 and 2 carried into 31.1. History — as of 2026-09-12: built and locally green; CI not run. Criteria 3 and 4 PASS; 1 and 2 only partly demonstrable without the demo stack. One enforced invariant was deliberately changed (the binary-wide `net/http` ban, replaced by a per-package one) and one role was widened (`anomaly-detector` SELECT on `connections`) — both argued in §5 and both wanting a human eye. Q12 answered: both surfaces exist. (Carried from the retired Q12: Phase 30 field 4 asked capture for DNS resolvability, TLS certificate expiry and reachable ports, and built them as passive CONFIGURED facts — `component:X dns_resolves` and the like — that stop at a handshake, reading field 17 as "no application requests". Phase 31's own field list names `probe.net.dns_resolve`, `probe.net.tcp_connect` and `probe.net.tls_validity`. **Phase 31 must either re-site them as probes or state that both exist and why.**) **Review 2026-11-03:** every open item decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31. To complete: the human commits, then `/ci` green on the merge result, then merge. |
| 31.1 | Close the probe loop | **complete** | **Signed off 2026-11-04** (architecture session): PR #20 (`4f69ab3`), CI green on the merge result (run 41789133416). Criteria 2 and 4 refined and the auditor's risks decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31.1. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.1, all 17 fields. Phase 31 is merged; the branch `phase-31.1-probe-loop` is cut from `origin/main` = `a3f110a`, with the sign-off as its first commit. Order within the phase: the two gate repairs first — the boundary allowlist (it must exist before anything else lands under `cli/internal/`) and the emptied `.trivyignore` — then expectations, then data sources, then the demo-stack criteria. Replace the whole of §5 with this run's report. Do not stage `shared/uv.lock`. |
| 31.2 | Present what works | **complete** | **Signed off 2026-11-04** (architecture session): PR #21 green on every job; the review's five corrections and the lockfile change verified on disk in `a18c73e`, with the self-check's numbers evidenced in §5. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. **Go-ahead 2026-11-04:** the branch `phase-31.2-present-what-works` exists, cut from `origin/main` = `4f69ab3`. Read Phase 31.2 in the plan including "Carried in from Phase 31.1". **Review 2026-11-04 (before CI):** justfile fix ratified with one change (types generated from the lockfile, as CI does); criterion 4 refined; five README and LIMITS corrections to make on this branch before merge — `DIAGNOSTIC_PLAN.md`, end of Phase 31.2. The last-admin guard is Phase 32's third item. |
| 32, part 1 | The isolation walk | **complete** | **Signed off 2026-11-04** (architecture session): PR #22 (`972f288`), CI green on the merge result with the fault library 6/6 on Linux (run 41815764073). Criteria 1 and 3 refined; decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — all 17 fields, read with "How Phase 32 is run" at the end of the section, which wins where they differ. This run is **part 1 only: the walk, in the binary** — no migration, no API, no frontend, no worker change; those are part 2. Order: the two carried-in items first (CONFIGURED values rendered as shapes; the generated catalogue mirror), then the shared Investigation model and its conformance fixture, then `internal/isolate` and `culprit diagnose`, then the fault library and its CI job. Branch `phase-32-isolation-walk`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32, part 2 | The investigation in the control plane | **complete** | **Signed off 2026-11-04** (architecture session), subject to the quickstart verification on `main` recorded in §5. Merged via PR #23 (`a22da56`). Decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — "How Phase 32 is run", then "Part 2 — the investigation in the control plane" at the end of the section, which holds the work order, the criteria and what not to build. Branch `phase-32-control-plane`. Order: the carried-in items first (the token grant, the symptom's attestation, untested versus unexplored branches; then the last admin), then storage, the API, the view, the correlation engine's removal, and the quickstart, README and LIMITS last. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.1, part 1 | The system, on the Investigation screens | **complete** (PR #24 merged, run 41875987970 green) | **Reviewed 2026-11-04** (architecture session); look approved by Joshua on the screenshots. PR #24 (`bd29351`). Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. |
| 32.1, part 2 | Everywhere else | **complete** (PR #25 merged, `072fb4f`) | **Signed off 2026-11-05** (architecture session), subject to the final run on `e97189f` being recorded green — 32.2's first step. Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. History: 2026-11-04: `2a851ee`, PR #25; run 41916090503 red on `e2e` only (quickstart bootstrap, Linux bind-mount ownership), fixed in the justfile, awaiting commit and CI. SARIF upload accepted (`self-check` green). Screenshots of every route were committed for review and removed from the tree in Phase 32.2 (they remain in history at `072fb4f`). **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32.1 — "Joshua's review of the screenshots" and "Part 2 — everywhere else" at the end of the section, which hold the four review changes, the work order, the criteria and what not to build; field 14 as refined applies. Requirements: `docs/PRODUCTISATION.md` §2, §4, §7 and §8. First confirm with `gh` that PR #24 is merged with CI green; if not, stop. Follow the work order: the review changes first, the fresh-eyes review last. Branch `phase-32.1-part-2`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
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
| 40, part 2 | The new identity: the repository | **complete** (PR #50, `cdc5032`) | **Signed off 2026-11-19** (architecture session): runs 44386033657 and 44390448565 (the report) green on every job, read from GitHub; four mutations shown red; nothing lost in the move to `docs/GUIDE.md`; the README criterion amended; a stale LIMITS entry rewritten. Phase 40 is complete. Recorded in `DELIVERY_PLAN.md`, Phase 40, "Review of part 2". |
| 41 | The gate | **complete** (PR #51, `3928f0a`) | **Signed off 2026-11-19** (architecture session): runs 44503311197, 44516832208 and 44519127072 (the report) green on every job, read from GitHub; wall time 12.4 to 13.3 minutes, from 22.0 to 24.2; three mutations shown red; the target missed by about a minute and accepted, `e2e (stub)`'s quickstart build bounding it; caching not now; C3 carried. Recorded in `DELIVERY_PLAN.md`, Phase 41, "Review". |
| 42 | Ownership on the record | **complete** (PR #53, `bb92e48`) | **Signed off 2026-11-19** (architecture session): runs 44534379764, 44543993249 and 44546655296 (the report) green on every job, read from GitHub; `reuse lint` and the map rerun, two mutations shown red; the header commit insertions only; Q41 ruled (#3 fixed; #2 and #4 dismissed by the owner); `AUTHORSHIP.md`'s merge fact corrected. Recorded in `DELIVERY_PLAN.md`, Phase 42, "Review". |
| 43 | Authenticated | **complete** (PR #55, `090cc4b`) | **Signed off 2026-11-19** (architecture session): runs 44573995497, 44579250490 and 44581822123 (the report) green on every job, read from GitHub; every commit Verified; 56 action references pinned and two mutations shown red; the verifies to be tightened as C4. The delivery plan is complete. Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review". |
| 43, close-out part 1 | Q42 and Q43 | **complete** (PR #64, `527d965`) | **Signed off 2026-11-20** (architecture session): runs 44748685372 and 44750683640 (the report) green on every job, read from GitHub, `narration-parity` included; every commit Verified; the run's mutations confirmed, and five of the architecture session's own, one surviving (C5). Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the close-out, part 1". |
| 43, close-out | C4, the signer workflow, and C5 | **complete** (PR #65, `91f62fb`) | **Signed off 2026-11-20** (architecture session): runs 44760584788, 44766464671 and 44768657523 (the report) green on every job, read from GitHub; `cli-release.yml` by hand on the branch, 44758619408 and 44766453375, verified with both flags; every commit Verified; six mutations shown red by the architecture session. `main`'s push run 44798857512: green on every job, with `publish`'s guard and tightened verify passing on all five images. Phase 43 and the delivery plan are complete. Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the close-out, part 2". |
| — | Housekeeping: the Dependabot backlog | **complete** (PR #66, `b9ea38c`) | **Signed off 2026-11-21** (architecture session): runs 44803269241 and 44805484085 (the report) green on every job, read from GitHub; the six closed as merged; every commit Verified; each lockfile moved only its bump. `main`'s push run 44877153270: green on every job, `publish` included. Q45 ruled (dismiss alert #9: the path is unreachable, counted at runtime). Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the housekeeping". |
| — | Housekeeping, part 2: the last alerts | **complete** (PR #70, `ddb275e`) | **Signed off 2026-11-21** (architecture session): runs 44879138798 and 44880245200 (the report) green on every job, read from GitHub; #67, #68 and #69 closed as merged; alert #9 dismissed under Q45; every commit Verified. `main`'s push run 44881325932: red on `e2e (stub)` (the agent's Kubernetes and systemd recipes), where the same tree passed on the pull request; Phase 44 part 1's step 0 attributes it. Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the housekeeping, part 2". |
| 44, part 1 | The audit | **awaiting decision** (PR on `phase-44-audit`; the register in `FIELD_READINESS_PLAN.md` §5; the dashboard's rendering not covered) | **Brief (2026-11-21):** `docs/FIELD_READINESS_PLAN.md` §4, under §2's rules: map every surface (the legacy ones included, removing nothing); the journeys end to end; determinism, Go and Python parity, honest absence and gates that cannot fail; the backend, security (every exit an exfiltration path), reliability, performance, the interface at three widths, tests, and the documented path from a clean clone. No product change; the findings register in §5, `phase-auditor` re-running a sample, then stop for review. Branch `phase-44-audit` from `origin/main` = `ddb275e`; its first commit is the review (`../phase-44-brief.patch`, message `../phase-44-brief.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

**Standing task, not a phase — new advisories should be found on `main`, not
mid-phase.** *(Folded into Phase 32.2, 2026-11-05.)* Three times now — OpenSSL in September, then PyJWT, certifi and
urllib3, then aiohttp, Pillow, filelock, pyasn1 and the Caddy build, both on
2026-11-03 — advisories published against pinned dependencies while a phase
sat waiting blocked that phase's CI. Add a weekly `schedule:` trigger that runs
the build-and-scan job on `main` (the image push and `deploy` steps already
require `github.event_name == 'push'`, so a scheduled run cannot publish or
deploy). A red scheduled run is then fixed in its own small pull request.
Dependabot security updates, a repository setting Joshua can turn on, would
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
Phase:        44, part 1 — the audit (docs/FIELD_READINESS_PLAN.md §4)
Branch:       phase-44-audit, cut from origin/main = ddb275e. 95e1e77 the
              review (../phase-44-brief.patch, .txt; git apply --check
              clean; signed, %G? = G), then the register and this report.
              Pushed. Pull request: see CI below.
Run:          2026-11-21, by the owner's instruction (the brief).
Status:       AWAITING DECISION — the register is written and the review
              rules on it. Not every area is covered: the dashboard was not
              rendered (4.7), and the journeys through the control plane,
              the API-side recipes and the stack's edge cases were not run
              locally (below). No product code, test, workflow or
              dependency changed; nothing dismissed, bumped, published,
              released or deployed; the ruleset untouched; shared/uv.lock
              not staged.

STEP 0 — main's push run 44881325932 on ddb275e
  Read: gh run view 44881325932 --log-failed, and both e2e (stub) job
  logs in full (../audit-44/logs/). It failed at check_agent_recipes.sh:79,
  "FAIL: the agent image is not on the kind node", 1.5 s after kind load
  image-archive returned 0. PR #70's run 44880245200, same tree, same
  runner image (ubuntu-26.04 20261116.202.1), kind v0.33.0, kindest/node
  v1.37.0: the image was listed and the recipe passed.
  Attribution: an infrastructure flake inside kind's image import, not the
  code; the guard (added after run 42804120023) caught it as designed. Its
  exact cause is UNTESTED: nothing on that failure path prints the node's
  containerd state. First occurrence: over the last 100 runs, the other
  attempt-1 failures were an apt mirror outage (44522173729) and the Q42
  HOSTNAME record (44597852296, since fixed).
  Rerun: gh run rerun 44881325932 --failed -> attempt 2, conclusion
  success, every job green (e2e (stub), narration-parity and gate
  included). Recorded as F44-007 (S3, D6): diagnostics on that path, not a
  retry.

BASELINE (local, Windows, one gate at a time, in the foreground)
  just lint, typecheck, lint-imports (6 kept), check-schema-drift (22
  tables), test (api, scripts, shared 1998 passed, 6 skipped; worker 93;
  mcp_server 21; extractors 39), check_coupled_files.py, cli-test (18
  packages), cli-build, culprit check --fail-on=breaks_request_path, and
  LLM_PROVIDER=none culprit check: all exit 0. The fault library was not
  run locally.

THE REGISTER (FIELD_READINESS_PLAN.md §5): 92 numbers, 91 findings
  (F44-020 withdrawn: this run misread its own output; the auditor caught
  it).
  By severity: S1 6, S2 15, S3 40, S4 30.
  By label: VERIFIED 66, RISK 25.
  By area (a finding may have two): core 22, security 20, readiness 18,
  interface 14, backend 13, legacy 7, tests 6, reliability 5, parity 1,
  performance 1.

  S1
    F44-001  culprit intent prints an extractor's stderr unredacted (a DSN
             password, in text and JSON)                       VERIFIED
    F44-002  the shared credential pattern misses 13 of 15 common shapes
             (DB_PASSWORD=, redis://:pw@, ?access_token=, Bearer, JSON
             and YAML password ...); check's SARIF carries one   VERIFIED
    F44-003  culprit check imports the target's Python and writes
             __pycache__ into the target repository (the GUIDE tour,
             followed exactly)                                VERIFIED
    F44-004  Go's RedactReading skips []string: a JWT audience holding a
             DSN leaves in probe JSON                         VERIFIED
    F44-005  agent tasks keep probe inputs (a token) verbatim and serve
             them back                                RISK (partly shown)
    F44-006  the agent's audit log and outbox take raw error text with a
             DSN                                              VERIFIED
  S2
    F44-008 publish before gate on main; F44-009 the quickstart over a
    pre-Phase-35 env file dies in a migration traceback (on this machine);
    F44-010 an Alembic merge read as three heads; F44-011 WORKERS=1 vs 4
    as different kinds of value; F44-012 the process adapter captures the
    shell's own variables (Q42's class); F44-013 Kubernetes capture marked
    complete from the template only; F44-014 a claimed agent task never
    expires; F44-015 one sign-in rate-limit bucket behind Caddy; F44-016
    the documented path needs Git Bash, and cli-build writes no .exe on
    Windows; F44-017 restore never tested; F44-018 nothing fails CI when
    nothing was checked; F44-019 no field-trial runbook (the draft is in
    ../audit-44/notes); F44-021 --change action: unredacted by the CLI;
    F44-022 422 messages quote values; F44-023 no data framing for
    system text reaching the narrator and MCP agents.

COVERAGE (the full record is in §5 of the plan)
  Covered by reading: every area 4.1-4.9 (five read-only auditors in
  parallel; their notes in ../audit-44/notes/).
  Run here: step 0; the baseline; intent, check and SARIF twice each,
  identical once ids and times are removed; 13 mutations (two survive in
  isolate: F44-024); secrets through every CLI exit and MCP; 14 edge
  cases; start-up (median 56 ms, n=20), check (median 7.3 s, n=5), the
  binary (13.96 MB), the dashboard bundle (about 171 kB gzip first load,
  under its 200,000-byte budget); go test -cover; the GUIDE tour steps
  0-2 on Windows.
  NOT covered, and why:
   - 4.7 the dashboard at 1440/768/390: `just quickstart` failed here
     (F44-009), and the screenshot script, which signs in with the
     quickstart's admin account from infra/.env.prod, was refused by this
     session's permission classifier. No screenshot exists. UNTESTED.
   - 4.2 the journeys through the agent, the control plane and MCP against
     the demo stack; 4.5's stack conditions (kubectl denied, a container
     exiting mid-capture, clock skew, an interrupted verify, concurrent
     requests, a control-plane restart); 4.6's capture and walk time
     against environment size, API latency, and the statement and N+1
     probes on Culprit's own API. All need the stack. CI's fault library
     and e2e cover the journeys (green on 44881325932 attempt 2); the rest
     is UNTESTED.
   - 4.3 not all 19 roles' grants against PERMISSIONS.md (three read);
     Redis authentication (a grep was refused).
   - 4.4 a full git log -p sweep for secrets, and Trivy.
   - 4.8 Python coverage; 4.9 install.sh, the Linux fresh clone, the tour
     from step 3.

PHASE-AUDITOR (every S1 and fourteen others, re-run from fresh copies in
../audit-44/rerun/): 18 reproduced, F44-004 and F44-006 raised to VERIFIED,
F44-005 partly, F44-020 not reproduced (withdrawn). Repository left clean
by it (isolate.go mutated and restored).

PROPOSED BATCHES (plan §5): 1 S1 and security; 2 correctness of facts;
3 reliability and the backend; 4 tests and gates; 5 the interface,
starting with the dashboard audit not done here; 6 documentation and the
first run; 7 legacy, after the owner's decision.

QUESTIONS FOR THE OWNER (plan §5): code execution on the target (import
or --no-import); the legacy surfaces; secret-scanning alert #1 and
whether /ci gates on secret scanning; permission for the dashboard run
and this machine's infra/.env.prod; whether main's publish waits for
gate; where a confirmed field finding is recorded. None is blocking for
the review; none is added to §3, since none stops this part.

../audit-44/
  logs/       step 0's logs, every gate's output, the quickstart log,
              go-cover.log, mutations.log, frontend-build.log
  notes/      the five auditors' notes (4.1-map, 4.2-core, 4.3-backend,
              4.4-security, 4.7-4.9-docs-cli-tests), auditor-sample.md,
              auditor-results.md
  scripts/    tour-setup.sh, edges.sh, canon.py, mcp_session.py,
              mutate.py, mutations.json, mutations2.json
  det/, edges/, tour/, rerun/   the inputs and outputs of every run
  register.md the register as inserted into the plan
  screens/    empty: no screenshot was taken

CLAUDE.md still says part 1 is "not started": this part commits only the
plan's §5 and the handoff, and the handoff wins.

CI
  (filled in after /ci)
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
