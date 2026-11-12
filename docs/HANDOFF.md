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
| Current phase | **36, part 2 — The walk sees slow** — implemented, **awaiting review**. PR #38 (`4c7bc6e`), CI green on every check (run 43235902449). Q26 (criterion 5) is for review, not blocking. Report in §5. |
| Previous phase | **36, part 1 — Budgets and the measurement: complete.** Signed off 2026-11-12; `main`'s push run 43218642206 on `716205f` green on every job (part 2's step 0). |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-36-walk`, from `origin/main` = `716205f`; PR #38. |
| Blocking questions | None. Q26 is open, not blocking. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q26 | **Phase 36 part 2, criterion 5** ("a non-GET request built anywhere in `internal/probe` is refused at one place, shown red by building one around it"). Built: one constructor (`newProbeRequest`), one rule (`checkMethod`), applied again by `methodGuard` under every client, and a source scan that fails on 26 ways around them. Three audits each found syntax the scan did not know (the third got a DELETE out with the scan green); each is a red case now, and the last fixes were not re-audited. A syntactic scan holds only against forms it knows, and `docs/LIMITS.md` now says so ("a guard against ordinary code, not a proof against deliberate code"). Accept that, or ask for something stronger — e.g. only `http.go` and `timing.go` in `internal/probe` may import `net/http` (a two-file allowlist, held like the network boundary), or a `go/types` analyzer in place of the scan. | 2026-11-12, Phase 36 part 2 run | Not blocking; part 2's review |

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
| 36, part 2 | The walk sees slow | **implemented, awaiting review** (PR #38, `4c7bc6e`; CI green, run 43235902449) | Every criterion met in tests and CI; criterion 5 with Q26. **Brief (2026-11-12):** `docs/PERFORMANCE_PLAN.md` Phase 36, "Part 2" at the end of the section: its decisions, work order, criteria and what not to build. Step 0: `main`'s push run on `716205f` green, then the phase-auditor re-audits `3be789e`. Branch `phase-36-walk` from `origin/main` = `716205f`; its first commit is the part 1 sign-off. Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 37 | The database: statements, plans and indexes | not started | `docs/PERFORMANCE_PLAN.md` Phase 37. "How Phase 37 is run" is written at the review before it. |
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
Phase:        36, part 2 — the walk sees slow
Branch:       phase-36-walk, from origin/main = 716205f (PR #37's merge);
              3da4cd4 the part 1 sign-off, 0a3c743 the work, f3997f0 the
              audits' findings, 3ceb0ee the re-audit's, 4c7bc6e the
              focused re-audit's. PR #38 (draft until this report).
Run:          2026-11-12, /next.
Status:       IMPLEMENTED; every local gate green; CI green on every
              commit (runs below); the audits' findings fixed, the last
              round (4c7bc6e) not re-audited. One question for review,
              not blocking: Q26 (criterion 5). Awaiting review.

STEP 0
  main's push run 43218642206 on 716205f: every job success, e2e (none),
  e2e (stub) and narration-parity included; deploy skipped.
  The phase-auditor re-audited 3be789e. Criteria 3 and 4 of part 1 CLOSED.
  Two OPEN, fixed here before anything was built on them:
  - urlIsOnRoute compared a canonical path and sent the raw URL: /ready/,
    //ready, /ready%3F/../../admin, /items/.., and a userinfo URL (sent
    as Basic auth) were timed against GET /ready's budget. Now urlOffRoute
    compares the escaped path as sent, segment by segment, and refuses a
    query, fragment or userinfo; red on part 1's check (14 cases, 280
    requests). Under culprit mcp a latency probe's address must be the
    endpoint of the budget's own component (and its scheme).
  - the Q25 scan missed Register reached through an alias of Probe and a
    generic interface. Catalogue.Register is unexported (register);
    TestCatalogueExportsNoRegistration, red on an exported one.

WHAT WAS BUILT (work order 1-6)
  1 Narration parity: _ms/_us/_seconds/elapsed are volatile only inside a
    reading's measured; ids and _at everywhere. A budget that differs
    between the legs is a difference (red before), samples are not.
  2 Part 1's corrections:
    - both budgets on a route judged from one run: Resolution.Also,
      Request.AlsoExpected, Outcome.Also; probe.Runner.RunOne returns one
      reading per budget. 50 requests counted at the server, two readings,
      each validating (red under part 1's resolution: one reading).
    - one method check: newProbeRequest builds every request, checkMethod
      is the rule, and methodGuard, a transport under every client,
      applies it again (and refuses a body) as a request leaves. A source
      scan of internal/probe fails on 26 ways to go around them (see Q26).
    - budget literals: model.BudgetLiteralProblem and
      culprit_model.latency.budget_literal_problem, from
      latency_conformance.json's budget_literals (1e3, 0o454, 0454,
      300_000, 300.0, +300, 0x12C, quoted, tagged, aliased ...). The Go
      loader reads the YAML node (Budget.UnmarshalYAML); the API composes
      the YAML, after its credential scan. Both refuse a merge key in an
      entry (budget_entries), budgets: through a top-level merge, and a key
      written twice (budget_manifests). Red without each check, in both.
  3 probe.http.latency discriminates latency_budget_exceeded; a timed-out
    request's setup is recorded (timeout_connect_us); planned joins the
    rule in Go and Python: a run cut short is inconclusive.
  4 internal/isolate/latency.go: the second pass runs only when the error
    pass found no root and nothing failing below the entry. Each component
    on the request path with a GET budget gets the hypothesis, tested on
    each budgeted route in subject order (supported on a fail, ruled out
    when all pass, unexplored otherwise). A pass rules out that component
    alone, so the pass descends the whole tree. The root is the deepest
    slow component with nothing slow below it; above it, propagation.
    model.SplitLatency judges setup alone and server time (total - setup)
    against the same budget: setup over with --from the caller roots at
    the connection (the component's hypothesis ruled out when its time
    passed); server over roots at the component; otherwise partial,
    naming both or "reaching X from this agent". The walk's remaining wall
    clock is each latency run's deadline. The rubric reruns the latency
    request and compares the same budget's reading. Verification runs a
    shared run once a round (same_run_as in the record; probe, target,
    environment and inputs must match). Placement places the probe on the
    component's endpoint (base_url) from wherever the binary runs.
  5 Fault library: latency diagnoses at component:inventory-service
    (root_kind latency_budget_exceeded, complete) and verifies; new
    latency-unbudgeted (the demo's manifest less budgets:) stays
    inconclusive, "no latency budget was judged"; new scenario
    latency-wrong-fix (600 ms) is not_resolved. results.json derived from
    expected.json (Docker is down here) and reproduced by CI's run, whose
    `git diff --exit-code` on it passed; README: 6 of 6 of 8 planted.
  6 LIMITS: "Added latency is isolated only against a declared budget"
    (replacing "is not isolated"), "Latency in the walk" (after errors;
    one vantage; a pass rules out one component; hop or component; what an
    unbudgeted component leaves unknown; a database below makes it
    partial; two slow branches; time and the wall clock), "What holds the
    GET-only rule, and what cannot", the URL rule, both budgets, the
    literal and YAML rules. PROBES ("In the walk"), PERMISSIONS (what the
    walk sends under net.http.outbound). README tour step 4: a budget, a
    slow /health, `culprit diagnose web --from web` roots at api — run for
    real on this machine (complete, reproduced, r3 p95 >= 402.443 ms) and
    `culprit verify` said verified after the sleep came out. CLAUDE.md.

CRITERIA (part 2)
  1 synthetic A->B->C, C slowed: root C; A->B, B->C propagation; no latency
    reading before the error pass found nothing; B fast & C slow -> C
                                                              PASS.
      isolate/latency_test.go (TestASlowCalleeIsTheRoot..., TestAFastCaller-
      RulesOutOnlyItself, TestLatencyIsNotAskedWhenTheErrorsExplain,
      TestASlowComponentAboveFastOnesIsTheRoot). The first build's
      children-only root rule was red on the B-fast case. Phase-auditor:
      mutations of the root rule and of the gate turn them red.
  2 from the same samples: hop / component / neither / outside  PASS.
      TestHopOrComponentFromTheSameSamples, recorded timings, no network.
  3 CI fault library: latency root inventory-service, verified after the
    fix, not_resolved after a wrong one; unbudgeted inconclusive saying
    no budget is declared                                     PASS in CI.
      runs 43228627279 (0a3c743) and 43231557369 (f3997f0): latency
      PASS (235 s), latency-unbudgeted PASS, verify/latency-wrong-fix
      PASS (312 s). The job is now ~11 min (was 3.5).
  4 both budgets: one run of 50 counted, two readings validated  PASS.
      TestARouteWithBothBudgetsIsMeasuredOnceAndJudgedTwice; through the
      commands, TestDiagnoseFindsASlowComponentAndVerifyJudgesItsFix
      (record same_run_as, verify 2 rounds x 2 runs x 50 + 2 requests).
  5 a non-GET built anywhere in internal/probe refused at one place,
    shown red                                  PASS for every form found;
                                                see Q26.
      TestEveryRequestIsBuiltInOnePlace, TestARequestBuiltAroundTheCheck-
      IsFound (26 ways), TestTheGuardRefusesAWriteAsItLeaves. Red on part
      1's TimeGet. Three audits each found syntax the scan missed (0a3c743:
      3; f3997f0: 9; 3ceb0ee: 6 incl. one that sent a DELETE); all are
      red cases now. 4c7bc6e was not re-audited.
  6 1e3, 0o454, 0454, 300_000 refused by the Go loader, the Python model
    and the API, from the shared fixture                      PASS.
      check/budgets_test.go, shared test_latency.py, api
      test_manifest_budgets.py; red without each check. NOT MET at 0a3c743
      (a merge key) and at f3997f0 (a top-level merge); CLOSED at 3ceb0ee
      by the focused re-audit.
  7 narration parity: a differing budget is red, samples are not  PASS.
      scripts/tests/test_narration_parity.py; red with 716205f's script.
  8 a latency probe near the walk's end stops at its deadline; the
    hypothesis is unexplored                                  PASS.
      TestALatencyProbeStopsAtTheWalksDeadline; the phase-auditor ran the
      real probe with a 1.5 s context: 22 of 50 sent, inconclusive "cut
      short", the reading validates.
  9 every PR check green, both e2e legs and narration-parity;
    LLM_PROVIDER=none changes nothing                          PASS.
      run 43235902449 and PR #38's checks (below).

DELIBERATELY NOT BUILT (part 2's list)
  No credential sent by any probe. No second vantage, no probe dispatched
  elsewhere. No latency from telemetry or a baseline. No early stopping
  inside a run (a run cut short at the walk's deadline is inconclusive,
  never judged on fewer requests than planned). No percentile but p50/p95.
  No change to how errors are walked (the second pass runs after them;
  existing isolate tests unchanged). Nothing for Phase 37.

GATES (local, Windows, Docker NOT running), on 4c7bc6e
  lint, typecheck, lint-imports (6 kept), check-schema-drift,
  check-no-llm-imports, check-invariants, check-scan-coverage, cli-lint,
  check_security_doc (75), check_coupled_files --base origin/main   PASS
  go test ./... (cli)                                                 PASS
  pytest without a database: api+scripts+shared 1228 passed earlier in
    the run; the latency, manifest, shared and scripts tests 1145 passed
    on 4c7bc6e; worker 65, mcp_server 4; extractors 31 + 22; frontend 19
  culprit check --fail-on=breaks_request_path; LLM_PROVIDER=none   exit 0
  NOT RUN locally: every database-backed test (api 321, worker 28,
  mcp_server 17 — Docker down), the fault library, e2e, quickstart,
  migration round trip (no migration). CI ran all of them.

AUDITS
  invariant-auditor (0a3c743): 1 violation, invariant 7 — a budget value
    that was not plain digits was echoed in the refusal, and the API ran
    the budget check before its credential scan, so a credential pasted as
    a budget reached stderr and the 400. Fixed in f3997f0 (no literal in
    either refusal; credentials first); tests in Go and the API. Risks
    taken up: same_run_as inputs, the mcp scheme. Left: AlsoExpected is
    filled only when the caller sets no Expectation (no caller does);
    a walk sends up to 50 GETs per budgeted component plus one rerun,
    under the existing grant (PERMISSIONS says so).
  phase-auditor: NOT COMPLETE at 0a3c743 (criteria 5, 6; findings A-G),
    NOT COMPLETE at f3997f0 (5, 6; E untested), focused re-audit at
    3ceb0ee: 6 and E CLOSED, 5 OPEN. Fixed in 4c7bc6e; not re-audited.
    Left: F — `planned` is optional in the rule, so a part 1 reading with
    no planned is judged on its samples (the probe always writes it).

DECISIONS TAKEN HERE (for review)
  - The second pass runs when the error pass found no root and nothing
    failing below the entry (partial reasons from the first pass kept).
  - The latency hypothesis's subject is the component; the walk asks each
    budgeted route as its own request target (the route subject).
  - The root rule looks at everything below, not only direct callees.
  - Two slow roots on different branches: the first depth-first is the
    root, the other listed, the diagnosis partial.
  - A database below the slow root makes it partial (no DB budgets yet).
  - Unbudgeted components not below the root are named in the statement
    without making it partial; with no root they make it partial.
  - Hop root: the component's hypothesis is ruled out by the same reading
    only when its server time passed; statements say "within" only for a
    side that passed.
  - same_run_as in the verify record (additive, version unchanged).
  - planned in the rule's inputs (optional; required for cut-short).
  - Verify's no-failing-reading reason adds "no latency budget was judged"
    when the investigation asked nothing about latency.
  - The demo's isolation wall clock was left at the default 2 min: the
    library's two ~45 s latency runs fit (CI: latency 235 s for the whole
    case, two diagnoses included). No isolation: field was added, because
    the API's manifest model does not know one.

IN THE PLAN, FOR CORRECTION
  - Criterion 5 asks a source property ("refused at one place, shown red
    by building one around it") that a syntactic scan can hold only
    against forms it knows: Q26.
  - "With B fast and C slow, the root is still C" implies the root rule
    reads everything below, not only callees; written that way here.

/CI
  run 43228627279 on 0a3c743 — SUCCESS, every job (fault-library incl.)
  run 43231557369 on f3997f0 — SUCCESS, every job
  run 43233833896 on 3ceb0ee — SUCCESS, every job
  run 43235902449 on 4c7bc6e (pull_request) — SUCCESS, every job:
           lint, typecheck, cli, test, migration-round-trip, self-check,
           kind-capture, fault-library, e2e (none), e2e (stub),
           narration-parity, build x5; publish, deploy skipped
  checks   gh pr checks 38: 22 pass, 2 skipping (publish, deploy), CodeQL
           and the four Analyze checks included
  alerts   none open (pr=38, refs/pull/38/merge, refs/pull/38/head)
  merge    origin/main = 716205f is an ancestor of the branch: the branch
           is the merge result

LEFT OPEN
  - Q26 (criterion 5), for review.
  - F: whether `planned` should become required on new latency readings.
  - The fault-library job's length (~11 min) as more latency cases land.
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
