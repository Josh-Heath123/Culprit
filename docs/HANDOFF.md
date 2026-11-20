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
| Plan of record | `docs/DELIVERY_PLAN.md` (Phases 40–43), **complete 2026-11-19**, with one close-out item, C4; Q42 and Q43, found on the way, are done. `docs/PERFORMANCE_PLAN.md` (Phases 36–39) and `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) are complete; D1–D8, the standing invariants and P1–P8 still bind. What comes after C4 is the owner's to decide. |
| Current phase | **43, close-out — C4, the signer workflow** — `not started`. Q44 is ruled. Brief: `docs/DELIVERY_PLAN.md`, Phase 43, "Close-out — C4, the signer workflow, as amended by Q44", with C5 first. Step 0: `main`'s push run 44755314601 on `527d965`, its `publish` included. |
| Previous phase | **43, close-out part 1 — Q42 and Q43 — merged as `527d965` (PR #64) and signed off 2026-11-20.** Runs 44748685372 and 44750683640 (the report) green on every job, read from GitHub; every commit Verified; five mutations by the architecture session, four red and one surviving (C5). Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review of the close-out, part 1". |
| Deploy | **Paused, 2026-11-05 — Joshua's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-43-c4`, to be cut from `origin/main` = `527d965`. Its first commit is the review, signed: `git apply ../phase-43-c4-review.patch`, then `git commit -F ../phase-43-c4-review.txt` (`docs/DELIVERY_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Open a draft pull request and mark it ready when the run report is committed; if the run stops on a question, it stays a draft. Run `just lint` before every push and the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. |
| Blocking questions | None. Q44 is ruled (`DELIVERY_PLAN.md`, Phase 43). |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q42, Q43 and Q44 are recorded at the end of Phase 43 in `DELIVERY_PLAN.md`. | | |

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
| 43, close-out | C4, the signer workflow | not started | **Brief (2026-11-20, as amended by Q44):** `docs/DELIVERY_PLAN.md`, Phase 43, "Close-out — C4, the signer workflow, as amended by Q44": C5 first; then every `gh attestation verify` names the workflow it runs in and `$GITHUB_REF`, with `publish` guarded to `main` and `v*` tags, held by `test_ci_workflow.py` against `ci-cd.yml`'s triggers; users given the commands in `docs/GUIDE.md`, linked from `SECURITY.md`; shown on a hand-started `cli-release.yml` run on the branch, and on `main`'s push run after merge. Step 0: `main`'s push run 44755314601 on `527d965`. Branch `phase-43-c4` from `origin/main` = `527d965`; its first commit is the review (`../phase-43-c4-review.patch`, message `../phase-43-c4-review.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        43, close-out — C4, the signer workflow
Branch:       phase-43-signer. bac6879 the review, 587959b the step-0
              report, e8442fe origin/main (03c309d) merged in, aec7317
              Q42 (b), eda2da3 the Q43 report, baea86d Q43, cc21141
              Q42 (a), then this report. Every commit signed (%G? = G).
              Pushed. Draft pull request #64.
Run:          2026-11-20, /next, with the Q42 and Q43 rulings
              (../q42-ruling.md, ../q43-ruling.md).
Status:       AWAITING DECISION — Q44, blocking. Q42 and Q43 done; C4
              not started: its decision 1 names refs/heads/main for
              images.yml's verify, and publish also runs on v* tags.

STEP 0 (unchanged from this morning's run)
  main's push run 44711807845 on 03c309d green on every job, publish
  attesting and verifying all five images on #56's action versions.
  44707603837 on 7f5feac red only at build (mcp_server)'s Trivy scan:
  mcp 1.29.0, CVE-2026-115563 (HIGH), fixed in 1.30.0 by #58.

Q43 — RULED (architecture session, 2026-11-20; ../q43-ruling.md)
  The shape.py / e4c1b7a9d2f0 pair in scripts/coupled_files.yaml is
  removed and its comment kept as history: it tested whether a file
  moved, not whether the vocabularies agree, and a check that can be
  passed only by gaming it is a defect. The worker/app/db.py pair, the
  check, its CI step, hooks and tests unchanged. The agreement is held by
  content: a database-free test that walks the Alembic chain by AST and
  compares the latest migration naming a *_value_shape_is_closed
  constraint with the four enums. e4c1b7a9d2f0 untouched; no empty
  migration; no bypass. To be recorded in DELIVERY_PLAN.md at review.

  baea86d — built
    api/tests/test_value_shape_vocabulary.py: reads every migration by
    AST (never imports), one head, the chain walked head to base with no
    orphan or cycle; the vocabulary's migration found structurally
    (e4c1b7a9d2f0 today; no revision id in the test); _VALUE_TYPES,
    _LENGTH_CLASSES, _FORMATS, _SCHEMES each without duplicates and equal
    as sets to ValueType, LengthClass, ValueFormat, ValueScheme. Anything
    missing fails it; it never skips (-rs: none). All four agree today:
    no drift to raise. test_value_shape_constraint.py's docstring that
    named the pair now names this test.
    Mutations, each red, each reverted:
      1 MUTANT added to ValueFormat: "_FORMATS and ValueFormat disagree -
        only in the model: ['mutant']".
      2 "uuid" removed from e4c1b7a9d2f0's _FORMATS: "only in the model:
        ['uuid']" (the migration restored with git checkout; untouched in
        every commit).
      3 a throwaway head migration (zz_throwaway_m3.py, down_revision
        a6c2e9d4f8b1, the current head) naming
        ck_configured_facts_value_shape_is_closed with _FORMATS one short:
        the test followed the chain to it - "zz_throwaway_m3.py:
        `_FORMATS` and ValueFormat disagree - only in the model: ['uuid']"
        (1 failed, 3 passed). Deleted; never committed.
    Elsewhere: git grep found no other claim of the coupling outside
    api/migrations (the hooks, CI step and auditor name the check, not
    the pair; ARCHITECTURE.md describes Phase 28's history).

Q42 — RULED (architecture session, 2026-11-20; ../q42-ruling.md)
  Reproduced on 587959b: 200,000 random 12-hex ids gave 0.774% of pairs
  not equivalent (theory 0.775%); abc, cafe, deadbeef were ip_address;
  format classification held by no shared fixture. Worse than raised:
  auth-audience's correct fix recreates order-service, the vantage, so
  about 0.8% of runs could judge a correct fix changed_underneath.
  Ruling: (a) IPv6 needs two colons, in Go and Python, with a formats
  section in shape_conformance.json read by both; (b) the process
  adapter does not shape a variable whose value equals os.Hostname(),
  keyed on the OS fact, process adapter only; (c) rejected - verify
  keeps counting every unexplained difference; also rejected: HOSTNAME
  by name, any name list, loosening narration-parity, a retry. To be
  recorded in DELIVERY_PLAN.md at review.

  aec7317 — (b) built
    processAdapter takes hostname func() (string, error), injected like
    environ (capture.Options.Hostname, probe.Sources.Hostname; nil is
    os.Hostname). A Known value equal to a non-empty hostname becomes
    EnvValue{Known: false}: exists kept, value_shape unknown, compared on
    presence alone, never value-allowlisted. Workload.Identity counts
    them; capture meta "identity.<component>" says how many, never a
    value. The capture tests' helper injects an empty hostname.
    Tests: capture TestTheRuntimesIdentityIsNotConfiguration (HOSTNAME
    and SERVICE_INSTANCE both unshaped; an unrelated key still shaped; an
    empty or unreadable hostname treats no key) and
    TestTheIdentityRuleReachesTheCapture (exists kept, shape unknown,
    meta present and free of the value); verify identity_test.go over
    real capture.Run process captures - HOSTNAME 3f9a2b7c1d0e ->
    123456789012 and -> 12345678901d: no difference; BUILD_ID (not the
    hostname) 3f9a2b7c1d0e -> 123456789012: exactly one value_shape
    difference.
    Mutations, each red, each reverted:
      M2 the rule removed: verify TestARecreatedContainersHostnameIs-
        NoDifference FAIL; both capture tests FAIL.
      M3 the rule keyed on key == "HOSTNAME": capture
        TestTheRuntimesIdentityIsNotConfiguration FAIL ("SERVICE_INSTANCE
        holds the hostname but was taken as configuration"; "Identity = 1,
        want 2").
    LIMITS: "A process capture does not shape the process's own hostname
    (Q42)". No UPGRADING note for (b) (accepted by Q43's ruling:
    Equivalent compares on presence when either side is unknown).

  cc21141 — (a) built
    The IPv6 branch is ^\[?[0-9a-f]*:[0-9a-f]*:[0-9a-f:]*\]?(?::\d+)?$ in
    shape.go and shape.py. shape_conformance.json gains `formats`, 32
    cases, read by Go's new TestFormatsMatchTheSharedFixture and Python's
    test_format_matches_the_shared_fixture (Python's own list removed).
    Checked by script against the ruling: all 14 of its cases present and
    right, and all 18 of Python's earlier cases.
    Mutation M1, red and reverted: the old branch ^\[?[0-9a-f:]{3,}\]?
    back in both languages - Go and Python each red on the same five
    cases (3f9a2b7c1d0e, deadbeef, cafe, abc, ab:cd).
    UPGRADING: "A capture from before an upgrade may shape a hex value
    differently (Q42)"; LIMITS points to it. No vocabulary change (held
    by baea86d's test).

GATES (local, Windows, one at a time, in the foreground)
  just lint: green before every push. just typecheck: green.
  just test: green (api, scripts and shared 1990 passed, 6 skipped -
  none of them new; worker, mcp_server and extractors passed).
  just cli-lint: green. just cli-test: green, 18 packages; the check
  eval suites (cli/testdata) unchanged. check_coupled_files.py: no
  violations across 1 declared pair. The README's self-check figures:
  just self-check-coverage, then check_readme.py --self-check: true.
  The fault library was not run locally; results.json and expected.json
  are untouched.

CI
  Draft pull request #64. Run 44748685372 (pull_request) on cc21141, the
  merge result (origin/main 03c309d already in the branch since e8442fe):
  conclusion success. Every job success - lint, cli, test, typecheck,
  migration-round-trip, kind-capture, self-check, the five builds (Trivy
  included), fault-library 1-4 (each writes results.json from the run and
  fails on git diff --exit-code: unchanged), e2e (none), e2e (stub),
  narration-parity, gate; build/publish and deploy skipped, as on every
  pull request. gh pr checks 64: every check pass or skipping, CodeQL
  and its four analyses included. Open code-scanning alerts: none
  (queries pr=64, ref=refs/pull/64/merge, ref=refs/pull/64/head all
  empty). Verdict: green on the merge result, for Q42 and Q43. One run
  cannot prove a 0.8% fix; the unit tests and mutations are the proof.
  The pull request stays a draft: C4 is not built.

C4 — NOT STARTED (Q44)
  Decision 1 confirmed on the run: the certificate on main's images
  (run 44711807845, frontend@sha256:2b29c57e…, both the SLSA provenance
  and the CycloneDX SBOM) names Build Signer URI and SAN
  .github/workflows/images.yml@refs/heads/main, Source Repository Ref
  refs/heads/main, trigger push - the called workflow, not ci-cd.yml.
  But ci-cd.yml runs on push to main and to tags v*, and images.yml's
  publish runs on both ("publish, which runs on main and tags";
  images.yml line 255 pushes :<tag> when the ref is refs/tags/v*). A
  verify fixed to --source-ref refs/heads/main would fail the first
  release's publish. Raised as Q44; nothing of C4 built.

NOT DONE (stopped at Q44)
  C4's four decisions, the hand-started cli-release.yml run, the
  auditors. The ruleset and every action version untouched; nothing
  published, released or deployed. shared/uv.lock not staged.

TO RESUME
  Rule Q44. Then C4 on this branch.
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
