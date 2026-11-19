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
| Plan of record | `docs/DELIVERY_PLAN.md` (Phases 40–43), from 2026-11-18. `docs/PERFORMANCE_PLAN.md` (Phases 36–39) and `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) are complete; D1–D8, the standing invariants and P1–P8 still bind. |
| Current phase | **43 — authenticated** — `not started`. Brief: `docs/DELIVERY_PLAN.md` §3 (D7) and Phase 43, with "Brief (2026-11-19)" at its end: the signing key made and added first. Step 0: `main`'s push run 44563572561 on `bb92e48`, and the code-scanning alerts' states. |
| Previous phase | **42 — ownership on the record — merged as `bb92e48` (PR #53) and signed off 2026-11-19.** Runs 44534379764, 44543993249 and 44546655296 (the report) green on every job, read from GitHub; `gate` required and shown to block (#54). Q41 ruled: #3 fixed, #2 and #4 the owner's to dismiss. Two mutations shown red by the architecture session; `AUTHORSHIP.md`'s merge fact corrected. Recorded in `DELIVERY_PLAN.md`, Phase 42, "Review". |
| Deploy | **Paused, 2026-11-05 — Joshua's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-43-signed`, to be cut from `origin/main` = `bb92e48`. Its first commit is the review, signed: `git apply ../phase-42-review.patch`, then `git commit -F ../phase-42-review.txt` (`docs/DELIVERY_PLAN.md`, `AUTHORSHIP.md`, `docs/HANDOFF.md`, `CLAUDE.md`), once step 0 has made and configured the signing key. Open a draft pull request and mark it ready when the run report is committed. Run `just lint` before every push and the local gates one at a time, in the foreground. Do not stage `shared/uv.lock`. Do not run the fault library locally. |
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
| 43 | Authenticated | not started | **Brief (2026-11-19):** `docs/DELIVERY_PLAN.md` §3 (D7) and Phase 43, with "Brief (2026-11-19)" at its end: the signing key made by Claude Code and added by the owner as a signing key, git configured for this repository alone; every commit Verified; every external action pinned to a SHA, held by a test; Dependabot for the actions; provenance and SBOM attestations on what `main` publishes, verified in the job; permissions held to a declared table. Step 0: `main`'s push run 44563572561 on `bb92e48`, and the code-scanning alerts' states. Branch `phase-43-signed` from `origin/main` = `bb92e48`; its first commit is the review (`../phase-42-review.patch`, message `../phase-42-review.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |

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
Phase:        42 — ownership on the record (with C3, carried from Phase 41)
Branch:       phase-42-ownership, from origin/main = 3928f0a. 7edfc39 the
              review (../phase-41-review.patch); 9f5a98a C3; 49fa66c the
              SPDX headers (insertions only); dc6e835 REUSE.toml, the map
              and the documents; 0716dee the audits' findings; then this
              report. PR #53, a draft.
Run:          2026-11-19, /next. Local gates one at a time, in the
              foreground; just lint before every push. The fault library
              never run locally.
Status:       Q41 RULED and carried out (below); ONE STEP LEFT, the
              owner's. CI run 44543993249 on 3aeeaf4: every job green, gate
              included; every PR check passes (26 pass, 2 skipping, CodeQL
              included). The ruleset now requires gate: the throwaway pull
              request read BLOCKED. But alert #2 is still OPEN, and #3 is
              dismissed as "won't fix" with #4's comment: the ruling's two
              dismissals look to have been applied to #3 and #4 instead of
              #2 and #4. Claude Code dismisses nothing, so the pull request
              stays a draft until #2 is dismissed (and #3, now fixed in the
              code, is left to close by itself or reopened, as the owner
              prefers).

Q41 — RULED 2026-11-19 (architecture session), CARRIED OUT
  The question: three code-scanning alerts, open on main since
  2026-11-04, failed PR #53's CodeQL check once the headers put a line
  into every file. The ruling:
  #3 py/clear-text-logging-sensitive-data, scripts/bootstrap_env.py: FIXED,
    not dismissed (3aeeaf4). bootstrap_env.py --local no longer prints the
    generated admin password; it prints where it is ("the admin's password
    is QUICKSTART_ADMIN_PASSWORD in infra/.env.prod"). just quickstart's
    final local message, read from that file, is unchanged. The justfile's
    CI-only filter of the printed line is removed (nothing left to hide);
    comments and docs/INSTALL.md updated. test_bootstrap_env.py: main()
    prints no value it generated, local and VM alike; red with the old
    print put back. No test expected the line.
  #2 py/clear-text-logging-sensitive-data, api/scripts/apply_model.py: to be
    dismissed by the owner as won't fix (printing a component's new key
    once is the one way to deliver a key that exists only as a hash).
  #4 py/weak-sensitive-data-hashing, api/app/ingest_gateway/auth.py:
    dismissed by the owner as a false positive (256-bit random keys, not
    passwords).
  As GitHub holds them now: #2 open; #3 dismissed "won't fix"; #4
  dismissed "false positive"; #3's and #4's comments both the API-key
  text. Open alerts, repo-wide and on refs/pull/53/head: #2 only.
  The ruleset (step 4): gh api repos/Josh-Heath123/Culprit/rules/
  branches/main lists required_status_checks [{"context": "gate",
  "integration_id": 15368}], strict. Throwaway gate-check from
  origin/main (3928f0a), one failing test, PR #54 opened ready: its run
  44543951760 failed test and gate, and mergeStateStatus read BLOCKED
  (mergeable MERGEABLE) while pending and after the gate failed. PR #54
  closed unmerged; gate-check deleted on the remote and locally.

STEP 0
  1 main's push run 44522173729 on 3928f0a, e2e (stub), job 135553437405,
    "Install Chromium for Playwright": playwright install --with-deps
    ran apt-get, which could not reach the Ubuntu mirrors —
    azure.archive.ubuntu.com:80 "connection timed out" and
    security.ubuntu.com:443 "Could not wait for server fd - select (11:
    Resource temporarily unavailable)" — fetched 8.9 MB in 3 min 19 s,
    failed six font packages (fonts-ipafont-gothic, fonts-wqy-zenhei,
    xfonts-*), and exited 100 ("Failed to install browsers"). No test
    ran. Attributed: the runner's network to Ubuntu's archive, not the
    code (D6). gh run rerun --failed: attempt 2 green on every job, gate
    included (deploy skipped).
  2 The ruleset. Throwaway branch gate-check from origin/main, one test
    asserting 1 == 2 (scripts/tests/test_gate_check.py), PR #52 opened
    ready (not draft). Its run 44525066795: test failed, gate failed.
    gh pr view 52 --json mergeStateStatus: UNSTABLE while pending and
    UNSTABLE after the gate failed, with mergeable MERGEABLE — NOT
    BLOCKED. Ruleset 26460341 ("Protect Main branch", active, updated
    2026-11-19 14:32 +02:00) has strict_required_status_checks_policy
    true and no bypass actors, but required_status_checks is []: no
    check is required. No branch protection and no other ruleset applies
    (gh api rules/branches/main). PR #52 closed without merging, with a
    comment saying why; gate-check deleted on the remote and locally.
    The ruleset was not touched: the owner's step. To do: add the
    status check "gate" (from GitHub Actions) to the rule, then repeat.

C3 — TEST TIMEOUTS INSIDE JOB TIMEOUTS (9f5a98a, 0716dee)
  Every go test a job runs, in a step or in a just recipe it calls
  (dependencies included), now times out in at most half the job's
  timeout-minutes: cli's database step 20m -> 10m (job 20; its other go
  tests have Go's default 10m); just agent-e2e 30m -> 15m (e2e, job 30);
  the fault library in CI 30m -> 17m (job 35; just fault-library keeps
  30); kind-capture Go's default -> 5m (job 10: not named in the brief,
  the same rule, since a go test with no -timeout has Go's 10).
  test_ci_workflow.py reads them all (seven commands across four jobs).
  A -run pattern's | is inside quotes and does not end the command. Both
  audits found that the first version read only a single-unit -timeout,
  so -timeout 0 (no timeout), 30m0s and 1h30m passed as Go's default:
  fixed in 0716dee (whole Go durations; 0 or a non-duration read as
  never). Red: each of the four timeouts put back; e2e's job lowered to
  20; the fault library's set to 0, 1h30m and 30m0s. LIMITS' bullet on the
  two timeouts that could not fire is rewritten to the rule.

THE ELEVEN DECISIONS, AS BUILT
  1 49fa66c: 668 files gain two SPDX lines and a blank one, nothing else
    (1,982 insertions, no deletion; the phase audit compared every
    file): the copyright line (2026 Joshua Heath) and the licence line,
    AGPL-3.0-only (611) or Apache-2.0 under shared/, extractors/python/
    and extractors/node/ (57). (Not quoted as tags here: REUSE reads a
    tag in any file, Markdown included; it did, and the map check went
    red on this report until it was reworded.) Python, Go, TS,
    TSX, JS, CSS, shell, SQL, YAML, TOML, HTML, INI, Dockerfiles, the
    justfile, Caddyfile, go.mod, the systemd unit, .env examples, ignore
    and attributes files. Shebangs and the two doctypes stay first (25
    files). REUSE.toml for the rest, by file type outside the test data:
    JSON, Markdown, PNG, SVG, lock files, go.sum, VERSION, NOTICE,
    .gitkeep, and the Alembic template (its comments would be copied into
    every migration); cli/testdata/ and api/tests/data/ by directory. No
    byte a test compares changed: go test ./..., just test, the
    extractors', frontend's and hook tests all green with only the
    headers, and the self-check's figures still equal the README's.
    LICENSES/: AGPL-3.0-only and Apache-2.0 are this repository's own
    LICENSE texts; MIT and BSD-3-Clause are SPDX's. Every LICENSE stays.
  2 The fixtures: BSD-3-Clause, "2010 Pallets"; MIT, "2009-2014 TJ
    Holowaychuk", "2013-2014 Roman Shtylman", "2014-2015 Douglas
    Christopher Wilson" (from their LICENSE files, addresses left out);
    precedence override. Each fixture's culprit.yaml (added in Phase 28)
    is Culprit's.
  3 scripts/check_licensing_map.py (standard library) reads reuse lint
    --json and LICENSING.md's table: REUSE compliant; every file under a
    row with exactly its SPDX identifier (the most specific row wins);
    every path the table names holds a file. On its first run it found
    LICENSING.md's "everything else" without deploy/, and lock files
    under shared/ annotated AGPL. The table now names an identifier in
    every row (the fixtures separately, their manifests, deploy/); no
    licence changed. 943 files agree: 827 AGPL-3.0-only, 84 Apache-2.0,
    20 BSD-3-Clause, 12 MIT (942 in CI, without the untracked
    shared/uv.lock). test_check_licensing_map.py: 11 cases.
  4 reuse lint runs in just lint and CI's lint job, as
    `uvx --from 'reuse[charset-normalizer]==6.3.0' reuse lint --json |
    check_licensing_map.py -` (6.3.0, released 2026-10-30; the extra
    because libmagic is not on Windows). The pipe has no pipefail, and is
    safe: the script fails on a non-compliant report and on empty or
    broken input (both audits checked). test_ci_workflow.py holds the
    pins equal in both places. CLAUDE.md's "Licences" line.
  5 NOTICE: the holder; the licence split, pointing at LICENSING.md; the
    two fixtures (tags 3.1.0, 4.21.2); Inter and JetBrains Mono
    (@fontsource 5.3, OFL-1.1, copyright lines from their packages). The
    bundle's, binary's and images' dependencies named as not listed; in
    LIMITS.
  6 AUTHORSHIP.md: who directs, decides, reviews and merges, with
    pointers (the plans; HANDOFF's protocol; 51 of 51 merged pull
    requests merged by Josh-Heath123; 308 commits, 233 as Josh-Heath123
    and 75 as Joshua Heath, from 2026-08-02); how it is made (Claude in
    Claude Code and the architecture session; 109 commits with a
    Co-Authored-By: Claude trailer, and that a trailer is not a share);
    Anthropic's Consumer Terms, effective 2025-10-08, section 4 (the
    assignment of whatever rights Anthropic has in Outputs), paraphrased
    and dated 2026-11-19, read from the page; the US Copyright Office's
    Part 2 report (2025-01-29), from copyright.gov; South Africa's
    Copyright Act 98 of 1978, s 1(1) "author" (i), quoted from WIPO Lex
    (gov.za's pages gave 404 and SAFLII 403). No legal conclusion; says
    twice it is not legal advice. Its commands are pinned to 3928f0a and
    -L 200 (0716dee), so they reproduce its figures.
  7 CONTRIBUTING.md: issues and private security reports welcome; outside
    code not accepted, and pull requests closed, until a lawyer reads
    the agreement. The agreement: Harmony Individual Contributor License
    Agreement (HA-CLA-I) 1.0, 2011-07-04, the licence form (not an
    assignment); Joshua Heath as "We"; project Culprit. OUTBOUND: Option
    Five (any licence, including proprietary, in addition to the
    material's own), chosen because it keeps the owner able to offer
    Culprit under other licences as well as the AGPL, so a hosted or
    commercially licensed Culprit stays possible. Media licences,
    governing law and how to sign left open for the lawyer. Linked, not
    copied: the template is CC BY 3.0, and a copy would need its own
    licence row and could drift from the original.
  8 TRADEMARKS.md: "Culprit" and docs/brand/mark.svg (and wordmark.svg)
    unregistered marks of Joshua Heath, not registered anywhere; what is
    fine; a fork or a hosted modified version takes another name and
    mark, and may say "based on Culprit".
  9 CITATION.cff: no version or date (nothing released); validated by
    `uvx --python 3.12 cffconvert@2.0.0 --validate` in just lint and CI.
 10 SECURITY.md (root; docs/SECURITY.md stays the threat model and is
    linked): private vulnerability reporting, with a fallback until it is
    turned on; scope as the brief lists, the demo services out; main only
    (no release yet); seven days; no bounty.
 11 The README's author line links AUTHORSHIP.md and NOTICE: 299 lines;
    check_readme passes.
  No email address, student number or local path in any of these files
  (grepped, and the phase audit grepped again).

MUTATIONS SHOWN RED (applied to the real file, run, restored)
  REUSE and the map: a new .py with no header; a Go file's header
  removed; a shared/ file headed AGPL; LICENSING.md's shared/ row set to
  AGPL; deploy/ dropped from the table; the Flask annotation removed
  (reuse alone stays compliant, the files falling to cli/testdata/'s
  AGPL; the map catches it). CITATION.cff without title, and without
  authors. CI pinning reuse 6.2.0. C3: as above. The phase audit
  repeated these with its own (cffconvert 2.0.1 pinned; cff-version and
  message removed; a different Go file; api/zz_noheader.py): all red.

AUDITS
  invariant-auditor (7edfc39..dc6e835): CLEAN, no violation. One defect
    in the new gate (the duration parse), fixed in 0716dee. Risks: the
    kind test's 5 minutes has no measured CI time of its own (the whole
    job took 1.1-1.9 in the last ten green runs); cli-release.yml's go
    test sits in a job with no timeout, older than this phase and outside
    the rule's file; the
    tools' own dependencies float under uvx (a change fails closed).
  phase-auditor (7edfc39..dc6e835): every criterion MET by execution;
    three defects, all fixed in 0716dee: the duration parse; REUSE.toml's
    comment naming a test that does not exist; AUTHORSHIP's commands not
    reproducing its figures. It could not check the web sources (no web
    access); this run read them (above). Not re-run after 0716dee.

LOCAL GATES (Windows, one at a time, in the foreground, on dc6e835; just
  lint and the touched tests again on 0716dee)
  just lint (with reuse, the map and CITATION), typecheck, lint-imports
  (6 kept), check-schema-drift, check-no-llm-imports, check-invariants
  (migration symmetry over the 32 headed migrations), check-scan-coverage
  (330 files), check-frontend-tokens, cli-lint, cli-test: clean. just
  test: api 1,931 passed (6 skipped), worker 93, mcp_server 21, 39, node.
  Not run locally: the fault library (instructed), e2e.

CI (PR #53)
  44534379764 on dc6e835: success on every job (publish, deploy
    skipped), gate included, wall 11.5 min. The lint log: the map check
    "942 files ... agree", and "Citation metadata are valid". PR
    checks: 25 pass, 2
    skipping, 1 fail — CodeQL, on three open alerts: #2
    py/clear-text-logging-sensitive-data, api/scripts/apply_model.py:77;
    #3 the same, scripts/bootstrap_env.py:414; #4
    py/weak-sensitive-data-hashing, api/app/ingest_gateway/auth.py:69.
    All three open on main at the same code three lines up (74, 411, 66)
    since 2026-11-04, never dismissed. Code-scanning queries: pr=53 and
    refs/pull/53/head 3 each; refs/pull/53/merge 0. NOT GREEN (Q41).
  44543993249 on 3aeeaf4 (after Q41's fix): success on every job (publish,
    deploy skipped), gate included; 26 PR checks pass, 2 skipping, CodeQL
    passing. Open alerts: #2 (pr=53, refs/pull/53/head and repo-wide);
    refs/pull/53/merge none.
  main has not moved (3928f0a), so that is the merge result. This
  report's commit runs after it.

NOT BUILT
  No history rewritten; no licence changed; no header on test data or a
  generated file; no registered mark; no legal advice; no outside code
  accepted or invited; the CLA's text not copied; no SBOM (Phase 43). No
  alert dismissed or suppressed; the ruleset not touched.
  Owner, now: add "gate" to the ruleset's required checks, then repeat
  step 0's throwaway check. After merge: Software Heritage; private
  vulnerability reporting; secret scanning with push protection.
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
