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
| Plan of record | `docs/DELIVERY_PLAN.md` (Phases 40–43), **complete 2026-11-19**, with one close-out item, C4. `docs/PERFORMANCE_PLAN.md` (Phases 36–39) and `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) are complete; D1–D8, the standing invariants and P1–P8 still bind. What comes after C4 is the owner's to decide. |
| Current phase | **43, close-out — C4, the signer workflow** — `not started`. Brief: `docs/DELIVERY_PLAN.md`, Phase 43, "Close-out — C4". Step 0: `main`'s push run 44597852296 on `090cc4b`, its `publish` attestations included. |
| Previous phase | **43 — authenticated — merged as `090cc4b` (PR #55) and signed off 2026-11-19. The delivery plan is complete.** Runs 44573995497, 44579250490 and 44581822123 (the report) green on every job, read from GitHub; every commit Verified; two mutations shown red by the architecture session. Recorded in `DELIVERY_PLAN.md`, Phase 43, "Review". |
| Deploy | **Paused, 2026-11-05 — Joshua's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-43-signer`, to be cut from `origin/main` = `090cc4b`. Its first commit is the review, signed: `git apply ../phase-43-review.patch`, then `git commit -F ../phase-43-review.txt` (`docs/DELIVERY_PLAN.md`, `docs/HANDOFF.md`, `CLAUDE.md`). Open a draft pull request and mark it ready when the run report is committed. Run `just lint` before every push and the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. |
| Blocking questions | None. Q41 is ruled (§5). |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q41 is ruled and recorded in §5 (2026-11-19). | | |

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
| 43, close-out | C4, the signer workflow | not started | **Brief (2026-11-19):** `docs/DELIVERY_PLAN.md`, Phase 43, "Close-out — C4": every `gh attestation verify` names its signer workflow and ref, held by `test_ci_workflow.py`; users given the commands in `docs/GUIDE.md`, linked from `SECURITY.md`; shown on a hand-started `cli-release.yml` run on the branch, and on `main`'s push run after merge. Step 0: `main`'s push run 44597852296 on `090cc4b`. Branch `phase-43-signer` from `origin/main` = `090cc4b`; its first commit is the review (`../phase-43-review.patch`, message `../phase-43-review.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        43 — authenticated
Branch:       phase-43-signed, from origin/main = bb92e48. c3969b3 the
              review (../phase-42-review.patch); a787f96 the pins and
              Dependabot; 6d2bffc the attestations, the permissions table
              and LIMITS; f56b4e4 the audits' findings; then this report.
              PR #55. Every commit signed and Verified (below).
Run:          2026-11-19, /next. Step 0 first; local gates one at a time, in
              the foreground; just lint before every push. The fault library
              never run locally.
Status:       COMPLETE pending review. CI green on 6d2bffc (44573995497) and
              f56b4e4 (44579250490): every job, gate included; every PR
              check passes; no open code-scanning alert. main has not moved
              (bb92e48): the merge result. The one criterion that cannot be
              shown before merge — an attestation verifying on main's push
              run — is the first thing to read after it (below).

STEP 0
  1 main's push run 44563572561 on bb92e48, read by id: success on every
    job, deploy skipped.
  2 The code-scanning alerts, as read then (nothing dismissed or reopened
    by this run): #2 open, never dismissed; #3 dismissed "won't fix" by
    Josh-Heath123 (14:21:54Z), also marked fixed at 16:14:13Z, with #4's
    API-key comment; #4 dismissed "false positive" by Josh-Heath123. One
    open alert, #2. The owner then dismissed #2 ("won't fix"); read again
    before this report: #2 and #3 dismissed "won't fix", #4 "false
    positive"; none open.
  3 The signing key (decision 1): ed25519 at ~/.ssh/culprit_signing, made
    by ssh-keygen after checking that nothing existed there; no
    passphrase; comment "culprit commit signing", no address. Git, for
    this repository alone (git config --local): gpg.format ssh,
    user.signingkey the key, commit.gpgsign and tag.gpgsign true, and
    gpg.ssh.allowedSignersFile ~/.ssh/culprit_allowed_signers (the
    committer's address and the key, so git log --show-signature
    verifies locally). The public key was printed and the run stopped;
    the owner added it on GitHub as a signing key ("Culprit Signing
    Key"). Not added as an authentication key: the phase audit found it
    in user/ssh_signing_keys, and the account's public authentication
    keys (users/Josh-Heath123/keys) empty; user/keys itself needs a scope
    the token lacks. A dry-run sign-and-verify before the first commit
    was refused by the harness and not retried; the first commit was the
    test.

EVERY COMMIT VERIFIED (decision 2; GitHub's API, commits/<sha>,
  verification; and %G? = G locally for each)
  c3969b3 the review      verified=true reason=valid
  a787f96 pins            verified=true reason=valid
  6d2bffc attestations    verified=true reason=valid
  f56b4e4 audit findings  verified=true reason=valid
  (this report's commit is signed the same way; its verification is read
  after the push, below.)

THE SEVEN DECISIONS, AS BUILT
  1 Above (step 0).
  2 Above.
  3 Every external action pinned (a787f96): 52 uses: lines, sixteen
    actions, each to the commit its tag or branch named on bb92e48, with
    the most specific version tag at that commit as a comment. No version
    changed: checkout v4 -> v4.4.0, download-artifact v4.3.0, setup-go
    v5.6.0, setup-node v4.4.0, upload-artifact v4.6.2, setup-uv v5.4.2,
    build-push-action v6.19.2, login-action v3.7.0, setup-buildx-action
    v3.12.0, codeql-action v4.39.3, ssh-action v1.2.5, action-gh-release
    v2.6.2; trivy-action v0.36.0, kind-action v1.12.0, scp-action v0.1.7
    exact already; pypa/gh-action-pypi-publish's branch release/v1 ->
    v1.14.3. The two new actions, pinned the same way:
    attest-build-provenance v4.2.2 (2026-08-06), attest-sbom v4.1.0
    (2026-03-18), each the latest release at least two weeks old. Both
    audits resolved all 18 again through the API: every pin is its tag's
    commit. test_ci_workflow.py reads every uses: line of every workflow
    (.yml and .yaml) and the parsed uses: values, and fails on a tag, a
    branch, a short SHA, docker://, a missing `# vX.Y.Z`, or a flow-style
    step (f56b4e4). The local reusable workflow (./) is not an action.
  4 .github/dependabot.yml: github-actions only, directory /, weekly, one
    group of "*", so one pull request that must pass gate. Held by a test.
  5 Attestations (6d2bffc). images.yml: the build job writes each scanned
    image's SBOM (CycloneDX) with a second call of the same Trivy, after
    the blocking scan and apart from it (v0.36.0 writes each call's
    settings to a file it deletes before and after; the scan's inputs are
    unchanged; CI's log shows the SBOM step on all five images, "--format
    cyclonedx disables security scanning"), and hands it to publish with
    the image. publish, after pushing, reads the registry's digest from
    docker inspect (failing if there is none), attests build provenance
    and the SBOM by that digest with push-to-registry, and runs gh
    attestation verify twice, the second with --predicate-type
    https://cyclonedx.org/bom; under bash -e a failed verify fails the
    job. cli-release.yml: release attests its five binaries' provenance
    and verifies each (and that there are five), before the tag-only
    Publish.
    THE HAND-STARTED RUN: 44574017581, cli-release.yml, workflow_dispatch
    on phase-43-signed at 6d2bffc: success. release's steps all green;
    Publish skipped; publish-pypi and publish-npm skipped. "Attestation
    created for 5 subjects", Rekor logIndex 4001720906,
    github.com/Josh-Heath123/Culprit/attestations/69758459. The verify
    step exited 0 with the count check passed but printed nothing: gh
    attestation verify is silent on success without a terminal. So the
    evidence is the exit status, and GitHub's attestations API, which
    returns an in-toto SLSA provenance bundle for each of the five binary
    digests the job printed (two read by this run, all five by the phase
    audit). The step was left as it ran rather than changed after the
    proof. gh release list empty; no tag on the remote.
  6 Permissions (6d2bffc): test_ci_workflow.py holds every job's
    effective permissions in all three workflows to a declared table, and
    the table must name every workflow (f56b4e4). Only three jobs
    changed, each by exactly id-token: write and attestations: write:
    images.yml's publish, cli-release.yml's release (which keeps contents:
    write, now declared on the job), and ci-cd.yml's build, which calls
    images.yml: a called workflow's jobs hold no more than the caller
    grants, and the new table caught that it was missing. images.yml's
    build keeps contents: read; publish runs only on main and tags, so no
    pull request run gains a permission. The phase audit compared every
    job at bb92e48 and at HEAD and found the same.
  7 LIMITS: "What the signatures and attestations prove, and what they
    make public": the passphrase-less key; attestations in Sigstore's
    public log naming the private images and their digests; a
    hand-started CLI run's attestations; none before this phase; pins
    only as current as Dependabot.

MUTATIONS SHOWN RED (on the real files, restored)
  Pins: the pypi action back to its branch; trivy back to its tag; a short
  SHA; a pin's comment removed; the whole suite against the unpinned
  workflows; the new attest action by tag; a flow-style unpinned step; a
  new .yaml workflow. Dependabot: daily; a second ecosystem. Permissions:
  lint given packages: write; images.yml's build given id-token; publish
  without attestations: write; cli-release's workflow widened.
  Attestations: the SBOM attestation removed; publish's second verify
  removed; cli-release's verify removed; publish's verify given || true;
  the SBOM verify without its predicate. The phase audit repeated a
  number of these with its own.

AUDITS
  invariant-auditor (bb92e48..6d2bffc): CLEAN. The Trivy scan cannot now
    pass where it failed; every pin matches its tag; no permission
    reachable on a pull request; no injection path in the new run:
    expressions; neither verify can pass vacuously. Risks: R1, the publish
    path (digest lookup, verify against private ghcr.io images, push-to-
    registry) first runs on main after merge; R2, the verifies check the
    signing repository only (--repo), so a hand-started branch build
    passes the same check (in LIMITS); R3, test gaps — .yaml files and
    new workflows (fixed in f56b4e4), and the text-count verify check
    (fixed in f56b4e4).
  phase-auditor (bb92e48..6d2bffc): criteria 1, 3, 4 and decisions 1-7
    MET by execution (the passphrase not checked: ssh-keygen -y was
    refused to it); criterion 2 NOT RUN before merge, by the plan's own
    design. Defects, both fixed in f56b4e4: a verify softened with || true
    still counted; flow-style uses: escaped the pin check. Risk: the
    digest step under Docker's containerd image store (fails loudly if
    so). Not re-run after f56b4e4.

LOCAL GATES (Windows, one at a time, in the foreground, on 6d2bffc; lint
  and test_ci_workflow.py again on f56b4e4)
  just lint (with reuse, the map and CITATION), typecheck, lint-imports
  (6 kept), check-schema-drift, check-no-llm-imports, check-invariants,
  check-scan-coverage (330), check-frontend-tokens, cli-lint, go test
  -count=1 ./...: clean. just test: api 1,964 passed (6 skipped), worker
  93, mcp_server 21, 39. test_ci_workflow.py: 60 on f56b4e4. Not run
  locally: the fault library (instructed), e2e.

CI (PR #55)
  44573995497 on 6d2bffc: success on every job (publish, deploy skipped),
    gate included; 27 PR checks pass, 2 skipping; no open alert on pr=55,
    refs/pull/55/merge or refs/pull/55/head.
  44579250490 on f56b4e4: the same; 26 PR checks pass, 2 skipping (the
    27th on 6d2bffc was the hand-started run's release job, which GitHub
    attached to that commit); no open alert on pr=55, either ref, or
    repo-wide.
  44574017581: cli-release.yml by hand on the branch (above).
  main has not moved (bb92e48): the merge result.

FIRST AFTER MERGE (the criterion only main can show)
  main's push run: images.yml's publish, for all five images, must show
  both attestations created and both gh attestation verify calls exiting
  0. If the digest step finds nothing (R1, containerd), it fails loudly
  and the gate goes red; that is the case to look at first.

NOT BUILT
  No version changed; nothing published, released or deployed (the
  hand-started run attested only); no key added for authentication; the
  ruleset untouched (updated_at 2026-11-19T16:23:19+02:00, before this
  branch); no --signer-workflow on the verifies (R2, for the review).
  Owner, after merge: require signed commits in the ruleset and allow only
  merge commits; turn on Dependabot security updates. Then the delivery
  plan is complete.
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
