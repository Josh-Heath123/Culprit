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
| Current phase | **44, batch 3 — reliable under strain** — `in progress`: every decision done, F44-043 finished as Q49 ruled (2026-11-26), in `502f76a`; PR #74 marked ready only when `/ci` is green on the merge result. See §5. Brief: `docs/FIELD_READINESS_PLAN.md` §6, "Batch 3 — reliable under strain", under §2's rules: Q47's correction and Q48 first, then publish after `gate`, the quickstart's env file, a claim's deadline, and the API and worker under strain. Step 0: attribute `main`'s push run 45425513632 on `760cdfd`, red on `e2e (none)`'s quickstart where the same tree passed on the pull request; read the log, rerun, record both; fix it first if it is ambient. |
| Previous phase | **44, batch 2 — facts that hold — merged as `760cdfd` (PR #73) and signed off 2026-11-24.** Runs 45232041694 and 45234466757 (the report) green on every job, read from GitHub; the fault library unchanged; four mutations by the architecture session, all red. Q47 and Q48 ruled. Recorded in `FIELD_READINESS_PLAN.md` §6, "Review of batch 2". |
| Deploy | **Paused, 2026-11-05 — Joshua's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-44-b3`, to be cut from `origin/main` = `760cdfd`. Its first commit is the review, signed: `git apply ../phase-44-b3-review.patch`, then `git commit -F ../phase-44-b3-review.txt` (`docs/FIELD_READINESS_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Scratch work goes to `../audit-44/`, never into the repository. Open a draft pull request and mark it ready when the run report is committed; if the run stops on a question, it stays a draft. Run `just lint` before every push and the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. |
| Blocking questions | None. Q49 ruled 2026-11-26 (§5). |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | *None open.* Q49 was ruled 2026-11-26 (architecture session); the ruling is recorded in §5, and the architecture session records it in `FIELD_READINESS_PLAN.md` §6 with batch 3's review. | | |

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
| 44, part 1 | The audit | **complete** (PR #71, `6f64f69`) | **Accepted 2026-11-23** (architecture session): runs 44887167519 and 44888134489 (the report) green on every job, read from GitHub; 92 findings (6 S1, 15 S2), every S1 reproduced; `main`'s push run 45125493937: green on every job. The dashboard's screens move to CI (batch 5). Recorded in `FIELD_READINESS_PLAN.md` §6. |
| 44, batch 1 | Secrets stay in | **complete** (PR #72, `f694cb6`) | **Signed off 2026-11-23** (architecture session): runs 45169821500 and 45171911160 (the report) green on every job, read from GitHub; every S1 reproduction clean against the merged binary; three mutations of its own red. `main`'s push run 45216449983: green on every job. Recorded in `FIELD_READINESS_PLAN.md` §6. |
| 44, batch 2 | Facts that hold | **complete** (PR #73, `760cdfd`) | **Signed off 2026-11-24** (architecture session): runs 45232041694 and 45234466757 (the report) green on every job, read from GitHub; the fault library unchanged; four mutations of its own red. `main`'s push run 45425513632: red on `e2e (none)`'s quickstart, where the same tree passed on the pull request, and every image published anyway (F44-008); batch 3's step 0 attributes it. Q47 and Q48 ruled. Recorded in `FIELD_READINESS_PLAN.md` §6. |
| 44, batch 3 | Reliable under strain | **in progress** (Q49 ruled 2026-11-26; F44-043 done in `502f76a`; `/ci` on the merge result to come) | **Brief (2026-11-24):** `docs/FIELD_READINESS_PLAN.md` §6, "Batch 3 — reliable under strain": Q47 (a template's key change counts again) and Q48 (`unknown` fails the default gate) first; then F44-008, -009, -014, -015, -039 to -044, -047 and -050. Branch `phase-44-b3` from `origin/main` = `760cdfd`; its first commit is the review (`../phase-44-b3-review.patch`, message `../phase-44-b3-review.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        44, batch 3 — reliable under strain (FIELD_READINESS_PLAN.md §6)
Branch:       phase-44-b3, cut from origin/main = 760cdfd. b405ffb the review
              (../phase-44-b3-review.patch, .txt; git apply --check clean;
              signed, %G? = G), then one commit per decision. Draft PR #74.
Run:          2026-11-24, by the owner's instruction (the brief); resumed
              2026-11-26 on Q49's ruling (../q49-ruling.md, read in full).
Status:       EVERY DECISION DONE. Step 0, decisions 2-9, and F44-043 as
              Q49 ruled (502f76a); every fix with a test shown red first.
              The fault library's results.json unchanged (CI's git diff
              --exit-code passed, run 45454853674); not run locally. One new
              migration, d1e5b9c3a7f2, round-trip tested, altering and
              deleting no row. Nothing published, released or deployed; the
              ruleset untouched; shared/uv.lock never staged. PR #74 is
              marked ready only when /ci is green on the merge result.

Q49 — RULED 2026-11-26 (architecture session), amending F44-043's ruling.
  The architecture session records it in FIELD_READINESS_PLAN.md §6 with
  batch 3's review. The first ruling (cap /api/* at four times the largest
  body CI sent) was wrong: CI never sends an INTENT bundle (515,054 bytes
  here), a capture envelope posted with curl, or an agent's backlog.
  Ruled: one cap per kind of route, declared at the route.
  1. Two classes in one table, which the signed-route dependency and the
     tests read: bulk, 16 MiB (facts, captures, model/apply, divergences,
     both readings routes, verifications, investigations, task results,
     agents/me/audit); small, 64 KiB (14,214 x 4, rounded up), for
     everything else that takes a body. A route the table does not name
     fails a test.
  2. CULPRIT_MAX_BULK_BODY_BYTES raises the bulk cap; LIMITS gives both.
  3. Caddy's max_size on /api/* equals the bulk cap, held by a test that
     reads both.
  4. A 413 in F44-044's shape names the limit, and on bulk the setting.
  5. The agent batches by bytes under half the cap, keeps an entry that
     alone exceeds it locally with a reason in its log, and never retries
     a 413 unchanged.
  6. The five tests below, each red first. 7. The draft patch may be used.
  F44-093 is batch 4's to rule: recorded in the register, nothing changed.

STEP 0 — main's push run 45425513632 on 760cdfd. Failed log read (gh run
  view --log-failed): e2e (none)'s quickstart died building the frontend
  image, in `xcaddy build v2.11.7`: "verifying module: github.com/
  caddyserver/caddy/v2@v2.11.7: ... reading https://sum.golang.org/tile/8/
  0/x281/715: stream error: stream ID 3; INTERNAL_ERROR; received from
  peer". A transient HTTP/2 error from the Go checksum database, a
  third-party service: no input moved (the same pins built on the pull
  request the day before), and not the code. Rerun (gh run rerun
  --failed): attempt 2 success, 25 jobs success and deploy skipped;
  e2e (none) 138571286627, gate 138577977057. Attributed to the build's
  network: a finding with its cause, not a fix (D6), F44-093 below. No
  ambient commit.
  F44-093 (S4, VERIFIED): every image build fetches Caddy's modules and
  checks them against sum.golang.org (frontend/Dockerfile, xcaddy), so an
  outage of that service fails the quickstart, e2e and the image build.
  For the review: vendor or cache Caddy's module graph, or a sum-database
  policy; not a retry.

DECISIONS (red logs and mutations in ../audit-44/b3/)
2 c99d20a  Q47. A Kubernetes key names its source in its provenance: the
           template (kubernetes:deployment/), or the envFrom ConfigMap or
           Secret by name (model.ArtefactKubernetes*; Python's twin in
           capture_diff.py). Between environments a key one template lists
           and the other does not is a difference, worded "lists X in the
           Deployment's template, and <env>'s template does not; there it
           may come from a source Culprit cannot read", however incomplete
           either capture is; a key from a ConfigMap or Secret is compared
           only when the other capture shows a reading of that source;
           against INTENT an incomplete capture still proves no absence.
           Red: the fixture Go 3, Python 3 (4 new rows); verify's
           two-template test (verified, want changed_underneath); the
           env-diff corpus's new template-key-removed (missed); the capture
           test's sources (4). Two mutations of the engine's rules: red.
           kind-capture's expectation does not change (it asserts types and
           the one skip). Decision: keys only; an envFrom source renamed,
           dropped or emptied is not compared (LIMITS).
3 4534b8a  Q48. Severity.AtLeast counts unknown as degrades; Rank (report
           order) unchanged. The findings error says how many were unknown
           and why. Red: TestFailOnThreshold (2, want 3) and the message
           test. Mutation red. This repository's self-check: no
           divergences.
4 8106f7b  F44-008. ci-cd.yml's new `publish` job needs gate and calls
           images.yml at its publish stage (stage: publish), which runs the
           publish job alone, from the artifacts build kept; images.yml
           still signs, so every verify is unchanged. On a push (and a
           hand-started deploy of main, as before), never on a pull
           request; gate does not need it; deploy needs publish. Red:
           test_ci_workflow's "publish needs gate" (8). UNTESTED until
           main's push run after the merge (a tag cannot be cut).
5 724908e  F44-009. bootstrap_env.py --backfill adds every generated key a
           file lacks and touches none that is there; a URL is built from
           the password the file holds. The recipe runs it over a reused
           file. Red: 5 script tests. The laptop's infra/.env.prod untouched.
6 59ce3c0  F44-014. The deadline is 15 minutes (AGENT_TASK_DEADLINE_MINUTES):
           no task kind declares a timeout of its own, so the ruling's
           "kind's timeout plus a margin" is the margin alone. Applied at
           read (service.expire, an injected clock) and when the agent next
           speaks; a late result is kept and the task stays failed (the
           agent is answered 204 and carries on); the agent's next claim
           fails its own unfinished claim, since it runs one at a time — on
           the control plane, under agent-gateway's existing grants; the
           binary is unchanged. Red: 3 api tests. Mutation red.
7 bcea82a  F44-015 (X-Forwarded-For believed only from TRUSTED_PROXY_HOST,
           the compose files' `frontend`, re-resolved every 30 s), F44-041
           (migration d1e5b9c3a7f2: EXCLUDE USING gist (investigation_id
           WITH =, source WITH <>), with btree_gist; over rows recorded both
           ways it stops, naming the count and the query, changing nothing;
           the route answers the race 409), F44-044 (one shape, defined in
           app/errors.py; the 429 and the audit chain's 409 brought into it;
           frontend/src/lib/errors.ts reads it only), F44-047 (409),
           F44-050 (trimmed). Red: 8 api tests, the migration tests (no
           such revision), the race (both labels stored), the dashboard's
           errorMessage. Round trip clean. The ingest gateway's own 429
           still says {"error"}: not /api/*.
  86cb376  F44-043, the measurement, as ruled: request_bytes in the access
           line; scripts/request_sizes.py (tested); e2e reports the largest
           bodies; the fault library logs each case's. Run 45454853674: e2e
           11,019 and 11,015 bytes, the fault library 14,214 (19 cases).
           The cap itself: Q49, ruled 2026-11-26; 502f76a below.
  c9a5af5  ruff RUF100 in a decision-7 test, found by just lint.
8 fe392dd  F44-039 (a refused batch written one entry at a time; each entry
           Postgres refuses quarantined with "Postgres refused it: <class>
           (SQLSTATE ...)"; every entry refused raises; a database that
           cannot be reached acks nothing) and F44-040 (redis-py's Lock: a
           token, a Lua compare-and-delete, renewed every third of its TTL).
           Red: 4, the lock's against a real Redis. Mutations (no renewal;
           no per-entry fallback): red.
9 35c6b10  F44-042. LIMITS: a demotion or disabling takes effect within
           30 s; a password reset ends no session (up to 60 min); a token
           version is deferred.
  b5ea2d5  CI's self-check (run 45441945846) found AGENT_TASK_DEADLINE_
           MINUTES undescribed in api/.env.example (degrades; gate red):
           Culprit finding its own gap. Both new settings described; and
           pyright on the deadline tests' fixture. The local self-check,
           with the dashboard built: no divergences.

7 502f76a  F44-043 as Q49 ruled. api/app/body_limits.py holds the table
           (the ten bulk routes as ruled; 24 small), CULPRIT_MAX_BULK_
           BODY_BYTES (default 16,777,216, at least 65,536),
           BodyLimitMiddleware on every request (a declared Content-Length
           over the cap refused before reading; a chunked body the moment
           it passes it) and capped_body, which the signed-route dependency
           now reads before the signature (from the draft patch). A route
           in no class (a GET, a DELETE) is held to small. The 413:
           {"detail": "the request body is over this route's limit of N
           bytes (bulk); CULPRIT_MAX_BULK_BODY_BYTES on the control plane
           raises it"}, or "(small)" without the setting. Caddyfile:
           request_body max_size {$CULPRIT_MAX_BULK_BODY_BYTES:16777216} on
           /api/*, plus handle_errors 413 answering /api/* in the same
           shape (Caddy's own 413 has an empty body). Checked against
           caddy:2.11 in Docker with the cap set to 1000: 1000 bytes were
           proxied; 1001 bytes, declared and chunked, got the 413 with the
           JSON. `caddy validate` on the real file: valid.
           The agent (internal/transport) sends its audit backlog and
           readings in batches sized by bytes, under half the cap (and at
           most 1000 entries, the route's own limit). A 413 lowers the
           batch budget for every later batch, so no refused body is sent
           again. An audit entry that alone is over the cap is held and
           logged once ("audit entry N is B bytes, ...: kept in the local
           audit log and not sent"). The chain is in order, so nothing
           after that entry ships, and the agent carries on. An
           investigation or verification over the cap is refused before it
           is sent (one document cannot be split). The setting is described
           in both env examples; LIMITS: "A request body has a cap, one per
           kind of route". The self-check moves with the new setting: 1,768
           facts across 634 subjects, 536 unverifiable (README, GUIDE;
           check_readme true against a local --unverifiable self-check,
           with the dashboard built).
           Decisions for the review: (a) the cap is enforced on every route
           by middleware as well as in the signed dependency (the ruling
           names the dependency; a project-token or session route has
           none). (b) Caddy's 413 is given the API's shape, since through
           Caddy a body over the bulk cap never reaches the API. (c) The
           agent assumes the default cap and learns a lower one from the
           413. (d) POST /probes/{id}/run is bulk as ruled, though it takes
           no body today (it answers 503).
           RED FIRST (../audit-44/b3/q49/):
           - red-A*.log, the api tree without the implementation: the cap
             cases answered 401 where 413 was wanted (16,777,217 and
             65,537 bytes, declared and chunked); the table, Caddy and
             signed-route tests failed with no module.
           - red-go.log, the old transport with only BodyBytes and Logf
             added: 500 entries of 10 KB, an oversized entry, a lowered
             cap and 200 readings each got a 413, and the agent stopped.
           - The INTENT-size test (a 601,896-byte bundle stored, 201) is
             not red on the old tree, which had no cap. It is red against
             the single cap the first ruling would have built
             (mutations.log: facts as small, 413 at 65,536).
           - mutations.log, ten mutations, all red: a route dropped from
             the table (named in the failure); facts as small; the
             dependency back to request.body() (200 where 413 was
             wanted); Caddy's default at 16777215; the chunked count off by
             one; the setting dropped from the 413; Caddy's 413 without
             the setting; the agent's batch not sized by bytes, and a 413
             not lowering it (both loop, resending the refused body, until
             go test's timeout); an oversized entry made an error (the
             agent stopped).
           Tests: api/tests/test_body_limits.py (13: the table covers every
           route that takes a body and names no stale one; the bulk set is
           the ruling's; the numbers; Caddy reads the same value; Caddy's
           413; the middleware is installed; six cap cases at N and N+1);
           test_agents_api's signed-route cap (every signed route, declared
           and chunked); test_facts_api's INTENT-size bundle;
           cli/internal/transport/size_test.go (4).
  F44-093  Recorded in the register (S4, batch 4's to rule); nothing changed.

LOCAL GATES (Windows, one at a time, foreground) on 502f76a: just lint;
  typecheck (5 x 0 errors); lint-imports (6 kept); check-no-llm-imports;
  check-invariants; check-schema-drift; check-scan-coverage; just test:
  api, scripts and shared 2135 passed 6 skipped, worker 102, mcp_server
  21, 42; cli-test (19 packages ok); cli-lint; just self-check (no
  divergences). Not run, as nothing they cover changed: the migration
  round trip, extractors-test, the frontend's tests. The fault library was
  not run locally.

LOCAL GATES (Windows, one at a time, foreground) on b5ea2d5: just lint;
  typecheck (5 x 0 errors); lint-imports (6 kept); check-no-llm-imports;
  check-invariants; check-schema-drift; check-migration-round-trip (clean);
  just test: api, scripts and shared 2117 passed 6 skipped, worker 102,
  mcp_server 21, 42; cli-test (19 packages ok); cli-lint; extractors
  python 42, node 24; frontend 22. The fault library not run locally.

CI
  45433574819 on 4534b8a: success. 45440048763 on 8106f7b: cancelled by the
  next push. 45441945846 on 59ce3c0: red on typecheck and self-check, both
  fixed in b5ea2d5. 45454853674 on c9a5af5: e2e twice and fault-library
  1-4 success, results.json unchanged; typecheck and self-check red as
  above. 45459301798 on 63a671d (the report): red on self-check alone,
  "The README's self-check figures are this run's": README and GUIDE
  quoted 1,754 facts and 631 subjects, and the two settings b5ea2d5
  described make 1,766 and 633. Figures corrected in the next commit;
  check_readme true against a local --unverifiable self-check; committed
  as 35a42fc. 502f76a and this report: /ci's verdict on the merge result,
  in the PR.
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
