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
| Current phase | **38, part 1 — bundles: the build reader, `bundle_gzip_bytes_max` in `culprit check`, Culprit's own frontend under a budget in CI** — `not started`. Brief: `docs/PERFORMANCE_PLAN.md`, end of Phase 38: "How Phase 38 is run" (P6 amended: a built-in Go reader) and "Part 1 — bundles". Step 0: `main`'s push run 44076102588 on `4619099` green. |
| Previous phase | **37 — the database in the walk — signed off 2026-11-17** (PR #39–#44; part 3, the rest, merged as `4619099`). PR #44's last run 44072232611 green on every job, both fault-library shards included; the database shard reproduced `results.json` twice. Q36 accepted as applied; the wrong fix recorded as an action is accepted (Q20). Recorded at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-38-bundles`, to be cut from `origin/main` = `4619099`. Its first commit is the review: `git apply ../phase-37-signoff.patch`, then `git commit -F ../phase-37-signoff.txt` (`docs/PERFORMANCE_PLAN.md`, `docs/HANDOFF.md`). Open a draft pull request and mark it ready when the run report is committed. Do not stage `shared/uv.lock`. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Phase 37's questions (Q25–Q36) are ruled and recorded at the end of their phases in the plans. | | |

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
| 38, part 1 | Bundles | not started | **Brief (2026-11-17):** `docs/PERFORMANCE_PLAN.md` Phase 38, "How Phase 38 is run" and "Part 1 — bundles": its work order, criteria and what not to build. P6 is amended: a built-in Go reader, not the Node extractor (protocol 1 is INTENT only). Step 0: `main`'s push run 44076102588 on `4619099` green. Branch `phase-38-bundles` from `origin/main` = `4619099`; its first commit is the review (`../phase-37-signoff.patch`, message `../phase-37-signoff.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 38, part 2 | Lists | not started | Brief written at part 1's review. Decided already ("How Phase 38 is run"): a list route is bounded only where a bound is declared (`maxItems` in the spec, or `response_items_max`); no paging-parameter names. |
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
Phase:        37, part 3, the rest — the demo's empty category; the
              library's database fault; Q36; the documents
Branch:       phase-37-library, from origin/main = 883e9b2. 1f47027 the
              review, then 7de3689 (item 2), 641c92c and c6edc64
              (item 3), 41da346 (item 4), 5be8abd (Q36), 99d06c5,
              7395537, 91d9a6c, 5d5d9df, 9a305f9, then this report. PR #44.
Run:          2026-11-17, resumed from a working tree the last session
              left uncommitted (16 modified, 3 new files); kept whole.
Status:       COMPLETE pending review. CI green on 9a305f9 (run
              44067449151: every job, every PR check, no open alert);
              the database shard rerun once, results.json reproduced
              both times. Nothing blocking.

STEP 0
  main's push run 43497617319 on 883e9b2: success on every job, deploy
  skipped. Read by id.

THIS MACHINE
  The faults stack was taken down with its volumes (docker compose down
  -v) before anything else; nothing of this branch's was left running.
  The fault library was not run here: CI is its gate (two shards).
  TestDiagnoseFindsASlowComponentAndVerifyJudgesItsFix, alone on the
  quiet machine: PASS, 19.5 s.
  One container was run by hand, with the human's go-ahead, for the
  README tour's step 5 (postgres:16-alpine), and removed afterwards.
  The invariant auditor ran an api test selection that probably started
  a Postgres testcontainer briefly; nothing was left running. The one
  container still up (studysensei-db-1) is another project's.

Q36 — RULED MID-RUN (2026-11-14, architecture session), NOT A QUESTION
  demo-services/culprit.yaml loses inventory-service -> order-service and
  payments-service -> order-service. Neither service has an HTTP client;
  the edges were copied in Phase 27 from the old undirected adjacency.
  The "four-edge adjacency" comment now says each edge is a call the code
  makes. 635870479f4e (the backfill) is untouched; apply-model removes
  the two edges from a database that has them (they are culprit_yaml's).
  - expected.json: missing-index is complete; statement_contains "no
    index serves category"; remediation_contains "public.products
    (category, sku)"; the Q36 note is gone. Same relations, rubric and
    edges as the partial record: the database tree does not depend on
    completeness.
  - Existing cases: expected.json unchanged, and no result changed. All
    walk POST /orders from order-service, and the walk never followed the
    two edges (an edge back to a component already reached is not in the
    request-path tree).
  - What counts the demo's edges: nothing. No test, e2e spec or graph
    code counts them; api/tests/test_model_migration.py's four pairs are
    the backfill's history and stay. Four places cited the back edge as
    present: LIMITS (two), a comment in isolate.go and one in
    isolate_test.go; all now say "until Q36".
  - TestASlowEntryOverAMissingIndexIsComplete pins the new shape without
    Docker: an entry over its own route budget on server time, one
    background sql edge, four planes: complete, the same three edges.
  - One expectation changed because of Q36, found by CI: the database
    case's rubric discriminated is false, not true (9a305f9). It holds
    only when a reading rules out a competing hypothesis, and with no
    other branch on inventory-service's path none competes, as in
    network-partition. The first run (44064202665, fault-library (2))
    failed on that one assertion, in both subtests, and on nothing
    else; my record had carried true over from the partial case
    unchecked, and the unit test above asserts root and completeness,
    not the rubric.

ITEM 2 — Q35'S DEMO (7de3689)
  (1) FEATURED_CATEGORY = category-200, never seeded.
  (2) The products traffic alternates a bare GET /products with each
      seeded category in turn (itertools.cycle); no random.choice.
  (3) The 20 ms statement budget stays; its why states the mechanism
      and Q35's numbers.
  (4) GET /products: latency_p95_ms 30, from measurement on the faults
      stack (p95 3.1 ms at 0003, 108.5 ms at 0002; 100 timed requests
      from inside inventory-service with the traffic running). The why
      says so; test_manifest_budgets asserts it is declared.
  (5) Docstrings, data and DDL unchanged:
      - 0002_seed_products: "reading one category by a sequential
        scan ... tens to hundreds of milliseconds" replaced by the real
        mechanism: interleaved categories, the sku walk stopping early
        for a seeded category and walking the whole index for an empty
        one; not a sequential scan.
      - 0003_index_products_category_sku: "Phase 37 part 2 measured it
        within the 20 ms statement budget, where an index on category
        alone is not" replaced: the fault is an empty category (~75 ms),
        this index takes it to ~0.006 ms, and category alone goes unused.
  The faults stack's database, from ../phase-37-index-faults-stack.patch.

ITEM 3 — THE LIBRARY'S DATABASE FAULT (641c92c, c6edc64, 99d06c5, 7395537)
  - Planted in the database (0002) and the walk's tree (0001-0002);
    the extractor runs in every walk (Q33 (3)).
  - Known fix commit:1327410 (adds 0003), applied: verified.
  - Wrong fix: a category-only migration, in the tree and applied:
    not_resolved on probe.db.statement_budget. DEVIATION from Q33 (2)'s
    wording, which says "a commit": it is named
    action:added and applied a migration indexing products on category
    alone, because that migration is in no commit of the repository's
    history, and naming one would be the Q20 lie. The architecture
    session may prefer otherwise.
  - Walk fix (641c92c): planNodes read only []any, so a live walk saw no
    plan node; it reads the probe's []map[string]any too. Test red on
    the old code (shown).
  - The wrong fix's migration moved from cli/testdata/faultlib/ to
    demo-services/faults/ (99d06c5): check-scan-coverage found neither
    lint reached it. No root or exemption changed; 316 of 316.
  - test_no_fault_library_record_names_a_commit (Q20) failed once
    1327410 was named. Rewritten narrower, not dropped:
    test_only_the_database_fault_names_a_commit asserts the commits
    named are exactly [missing-index: commit:1327410], and six actions.
  - results.json gains missing-index (complete, verified) and
    missing-index-wrong-fix (complete, not_resolved). Written by hand
    from expected.json, because the library does not run here; CI's
    `git diff --exit-code` on it is what proves it. README's number:
    7 of 7 verified, 9 planted, a schema row; still labelled planted.
  - Two shards: database cases in shard 2, the rest in shard 1.
    TestTheFaultLibraryShardsCoverEveryCaseOnce: every case in exactly
    one shard, and the workflow's matrix is [1, 2].

ITEM 4 — THE DOCUMENTS (41da346, 91d9a6c, 5d5d9df)
  LIMITS ("The database in the walk": the entry rule, background edges
  said outright, partial, own traffic, Q35's shape, four planes, the
  unused index, the unapplied migration, the derived recommendation, the
  agent without migration INTENT; the two-edge rule was already there);
  PROBES ("In the walk"); PERMISSIONS; EXTRACTOR_PROTOCOL (db_schema
  says which columns lead an index, leads_index true and false);
  README's probe section and the tour's step 5.
  Tour step 5 was run before it was written (Windows, Git Bash): a
  million products, pgbench on an empty category (75 ms a call);
  diagnose COMPLETE, root schema:db/public.products.category,
  recommending (category, sku); verify VERIFIED. What the run taught:
  the sql edge is background and no db.metadata.read is granted, as in
  faults-inventory (else probe.db.connect is asked and refused); pgbench
  starts through sh -c (Git Bash rewrites a bare /tmp path).

CRITERIA (Q35 and the carried part 3, continued)
  Two runs of the database shard on 9a305f9, run 44067449151: job
  133988085395 (attempt 1) and job 133994469135 (attempt 2, gh run
  rerun --job). Figures are job 1 / job 2.
  At 0002: statement mean >= 30 ms, route p95 >= 2x budget     PASS:
    p95 98.0 / 96.6 ms; means 42.6, 42.2 / 41.1, 41.6 ms
  At 0003: mean < 2 ms, p95 <= half the budget                  PASS:
    p95 4.0 / 3.2 ms; four means 0.099-0.104 / 0.096-0.098 ms
  Category alone: mean > 20 ms, not_resolved, plan still on
    ix_products_sku                                             PASS:
    four means 41.7-42.3 / 40.6-41.8 ms; plan check passed
  missing_index complete, verified, not_resolved                PASS, both
  Determinism: same outcomes across two runs                    PASS: both
    jobs pass missing-index (complete, root category, (category, sku),
    verified) and missing-index-wrong-fix (not_resolved), and both
    jobs' "The committed results are this run's" step (git diff
    --exit-code on results.json) succeeded.
  Q33: the library's walks run the extractor                    PASS (CI:
    the migrations' INTENT is one of the four planes the root needs)
  Existing expected.json unchanged, results.json changes listed PASS (above)
  CI green, fault library <= 15 min per shard                   PASS:
    shard 1 11m18s, shard 2 10m39s (44067449151)
  The healthy stack: the quickstart at 0003 within both budgets NOT RUN:
    nothing gates it and the quickstart was not run on this machine.
    The faults stack at 0003 is held to both in CI (the second line).
  LLM_PROVIDER=none changes nothing                             PASS: the
    self-check is identical with it; the fault-library jobs run with none.

AUDITS
  invariant-auditor (1f47027..91d9a6c): CLEAN. The test rewrite is a
    narrowing; the move changed no root or exemption; no case can fall
    out of both shards. Risks: the wrong fix's wording (above);
    TestAShardKeepsTheOtherShardsResults checks shard 1 only; the
    route's budget locator budgets[2] depends on order (fails loudly).
  phase-auditor: every local criterion MET; field 17 not built; CI
    criteria NOT RUN HERE until this run. Its findings were fixed in
    5d5d9df (a stale test comment; the background sentence), and the
    quickstart criterion is recorded NOT RUN above.

LOCAL GATES (Windows, before 5d5d9df, which is comments and LIMITS)
  just lint, typecheck, lint-imports, check-schema-drift,
  check-scan-coverage, check_coupled_files --base origin/main: clean.
  just test: 1697 passed, 1 failed (the Q20 test, rewritten in 7395537,
  then 6 passed). just self-check: no divergences, 1712 facts across
  630 subjects. `culprit check` with LLM_PROVIDER=none: identical.

CI
  44064202665 on 5d5d9df: red on fault-library (2) only, on the rubric
    (above); every other job green.
  44067449151 on 9a305f9: success on every job; deploy and publish
    skipped. fault-library (1) 11m18s, (2) 10m39s; attempt 2 of (2)
    10m36s. Every check on PR #44 pass or skipping (CodeQL and its four
    analyses included); no open code-scanning alert (queried by pr=44,
    refs/pull/44/merge, refs/pull/44/head). main had not moved
    (883e9b2), so the branch was the merge result.
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
