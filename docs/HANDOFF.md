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

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35, with 31.1, 31.2, 32.1 and 32.2 inserted) |
| Current phase | **35, part 1 — The agent surface** — status `not started`. Brief in §4. |
| Previous phase | **34 — The verification loop and calibration: complete** (two parts), part 2 signed off 2026-11-11 by the architecture session. Merged via PR #33 (`0effc53`), every pull-request check green. Decisions at the end of Phase 34 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-35-mcp`, cut from `origin/main` = `0effc53`; its first commit is the Phase 34 sign-off. Lands through a pull request. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** §3 is empty. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q20 and Q21 were ruled 2026-11-10 (`DIAGNOSTIC_PLAN.md`, end of Phase 34): an `action` change kind in part 2; criterion 3 refined for a diagnosis with no failing reading, and latency detection left to Phase 36. | | |

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
| 35, part 1 | The agent surface | not started | **Brief (2026-11-11):** `DIAGNOSTIC_PLAN.md` Phase 35 — all 17 fields, read with "How Phase 35 is run" at the end of the section, which wins where they differ; then "Part 1" there for the work order, five criteria and what not to build. `culprit mcp` is served by the binary over stdio; the Python MCP server is not repointed. Branch `phase-35-mcp`. Lands through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 35, part 2 | The narrator | not started | Criteria written at part 1's review. |

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
Phase:        34, part 2 — outcomes in the control plane
Branch:       phase-34-outcomes, from origin/main = 2ef3da6 (PR #32's merge);
              its first commit is the part 1 sign-off (a15f79d). Commits
              690e778..HEAD. PR #33.
Run:          2026-11-10 (/next, the build) and 2026-11-11 (an e2e repair).
Status:       IMPLEMENTED; CI GREEN on PR #33 (run 42989682700, below). Not merged: the merge is the
              human's, after the architecture review.

WHAT WAS BUILT (work order 1-7)
  1 Carried in (690e778). Q19: api-reader reads agent_nonces (agent_id,
    seen_at) by a column grant and is refused `nonce` (f1a9c3d7e2b4). Q20:
    an `action` change kind in Go, Python and the conformance fixture (23
    accepted, 40 rejected, 12 touches), `--change action:<what was done>`;
    the fault library's three runtime fixes are named as actions, and a
    test holds the library to naming no commit.
  2 Storage. `verifications`, append-only as agent_audit_log is: triggers
    refuse UPDATE, DELETE and TRUNCATE to every role, the owner included; a
    CHECK holds `verified` to its three clauses. One new role,
    verification-writer, INSERT and nothing else (f2b7d4e9a1c6).
  3 The API. POST /investigations/{id}/verifications (project token or an
    agent, recorded which) re-judges with judge(); refuses re-runs before
    the investigation, a `was` that disagrees with the stored reading, a
    skipped reading, a verified_at before its own last run or after the
    server's clock, and a source contradicting an earlier one (409);
    redacts; never writes to the investigation. GET .../verifications,
    newest first. GET /outcomes/accuracy: each complete diagnosis's newest
    verification, per fault class (the root's subject kind) and source,
    every verdict counted, the denominator stated, inconclusive beside it.
  4 The agent. A walk keeps each reading's request and a before capture
    under the agent's own grants, beside its audit log. A `verify` task
    re-measures an investigation it diagnosed and posts the verification
    before its result; asked about one it did not diagnose, it answers
    inconclusive, holding no record of before. VerifySpec redacts every
    action's words at the choke point (invariant 11).
  5 The view (255fc9a). Verifications newest first — verdict, the three
    conditions, the change, planted or real, who recorded it; the rubric's
    `verified` from the newest. An admin asks an agent to verify from the
    page, naming the change; the diagnosing agent is the default.
  6 The README's number. The fault library writes
    cli/testdata/faultlib/results.json when every case passes; CI must
    reproduce it. `just accuracy-readme` renders the section with the
    function GET /outcomes/accuracy uses: 5 of 5 planted faults verified,
    two partial diagnoses not counted, "planted faults in our own demo
    services", not accuracy on a real system.
  7 LIMITS (nine entries), PROBES, PERMISSIONS, SECURITY, UPGRADING,
    ARCHITECTURE, README, CLAUDE.md, the database rule's role list.

CRITERIA (part 2) — evidence from the build run (commits 690e778, 255fc9a,
f329b11 and PR #33); not re-executed one by one in the repair run.
  1 api-reader reads agent_id, seen_at; refused nonce; agents screen
    still shows last request                 column-grant test; agents e2e.
  2 `action` holds in Go/Python/fixture, explains nothing a capture
    records; no library record names a non-commit   fixture; library test.
  3 refuses re-runs predating, `was` disagreeing, verdict judge() does
    not reach — a test each                   api tests (690e778, f329b11).
  4 no role can update/delete a verification, red with the trigger
    removed; investigation row byte-identical  trigger-removed test (UPDATE
    and DELETE, f329b11).
  5 end to end through an agent: verified, and not_resolved for a wrong
    fix, shown on the page                    `just agent-e2e` then
    `just e2e-verified` (verifications.spec.ts), both in CI's e2e job.
  6 an agent that did not diagnose it -> inconclusive, "no record of
    before"                                   `just agent-e2e`.
  7 /outcomes/accuracy gives exactly the seeded numbers; empty says so
                                              api tests.
  8 README number regenerated by a committed command, method, count,
    "planted faults" in so many words         `just accuracy-readme`; CI
    reproduces results.json.
  9 migration round-trips with verifications present; D8 allowlist
    unchanged; LLM_PROVIDER=none changes nothing   migration-round-trip job
    seeds a verification and a verify task.

AUDITS (build run, f329b11)
  invariant-auditor: ONE VIOLATION, fixed — an action's words were stored
    in agent_tasks.spec unredacted; VerifySpec now redacts, tested by
    reading the stored spec.
  phase-auditor: fixed — verified_at bounds; one source per investigation
    (409); the method states what `verified` measures; the README counts
    all seven planted faults; the trigger-removed test covers DELETE.

CI HISTORY ON PR #33
  42860211571 (on 255fc9a): red, e2e only — the agents journey asserted
    not_resolved for a verification an agent outside every component, with
    network grants alone, can only make inconclusive. Fixed in f329b11: it
    asserts the verification lands and is not `verified`.
  42862315900 (on f329b11): red, e2e only — the repair below.

THE E2E REPAIR (2026-11-11, 71f22fc)
  Failing test, verbatim:
    e2e/investigations.spec.ts:106:1 › the main journey works by keyboard
    alone (476ms)
      Error: never reached by Tab
        > 124 |     throw new Error("never reached by Tab");
          at tabUntil (frontend/e2e/investigations.spec.ts:124:11)
          at frontend/e2e/investigations.spec.ts:132:3
    1 failed, 1 skipped (verifications.spec.ts, by design), 17 passed.
  Screenshot (e2e-failures): /investigations/<complete> on its loading
    skeleton; focus on the header's "Users" link.
  Attribution: FLAKY — a race in the test, present on main; not this
    branch's code. Line 132 is the second tabUntil, toward the first
    edge-toggle. waitForURL resolves when the URL changes, before the
    tree's request returns; 60 Tabs take ~300 ms, and until the tree
    renders Tab only cycles the header. The test took 459 ms on main
    (42839202555) and 507 ms on this branch's previous run (42860211571):
    the margin was always a few hundred milliseconds. What made this run
    lose it is not shown; this branch's agents journey now runs a verify
    task immediately before, which is the likeliest load, unproven.
  Local reproduction (quickstart of this branch, Windows, port 8088):
    unmodified, the test PASSED (1.1 s) — no natural reproduction. Forced:
    the tree's response delayed 1.5 s by a temporary page.route -> FAILED,
    "never reached by Tab", as in CI; with the fix and the same delay ->
    PASSED (3.4 s). The probe was removed before commit.
  Fix: wait for the first edge-toggle to be visible before tabbing, as the
    list step already waits for its link. No retry, no longer timeout, the
    assertion and the 60-Tab bound unchanged; the target is still reached
    by Tab alone.
  Local e2e after the fix: 17 passed, 1 skipped, 1 failed — the agents
    journey, which cannot run on this machine: scripts/agent_recipe.sh
    compose-prepare needs sudo ("Sudo is disabled on this machine"). It
    passes in CI (42862315900: 13.8 s). Not this change.
  Met on the way, none of them CI's:
    - Docker's first build after Docker Desktop started failed DNS
      (proxy.golang.org: no such host); the retry built.
    - A local infra/.env.prod from before Phase 34 lacked
      VERIFICATION_WRITER_DB_PASSWORD; migration f2b7d4e9a1c6 refused to
      run, as UPGRADING says it will. The key was added by hand, at the
      human's terminal (Claude Code does not write credentials). CI
      generates a fresh env.
    - A second e2e run within a minute hit the sign-in rate limit (HTTP 429,
      LIMITS "The browser tests need the whole stack...") — waited it out.
    - The push printed "Bypassed rule violations for
      refs/heads/phase-34-outcomes: Cannot update this protected ref." The
      push landed; a ruleset on the phase branch that this account bypasses.
      Worth a look at the review: either the rule is meant for main only, or
      phase branches are meant to be protected and the bypass is too wide.
  Gates for this commit: oxlint and tsc on the spec clean; /verify not run
    (a test-only change: CLAUDE.md). Prettier reports the file, before and
    after this change alike; it is not a gate in CI or the justfile.

/CI — PR #33, for the repair commit
  commit   71f22fcc655d29d56509494cc2943907b9b9cf9e (merge result: origin/main
           2ef3da6 is an ancestor; merging it changes nothing)
  run      42989682700  CI/CD, pull_request, success
           https://github.com/Josh-Heath123/Culprit/actions/runs/42989682700
  jobs     lint, typecheck, cli, e2e, migration-round-trip, test,
           kind-capture, self-check, fault-library, build x5: success;
           publish and deploy skipped
  e2e      main journeys 18 passed, 1 skipped (verifications.spec, run
           next); the keyboard journey 601 ms — past the old margin, the
           wait held; the agents journey 14.6 s; `just e2e-verified`:
           verifications.spec.ts 1 passed (criterion 5 in CI)
  tests    api+scripts+shared 1299 passed / 4 skipped; worker 65; mcp 21
  checks   gh pr checks 33: 20 pass, 2 skipping, 0 fail (CodeQL included)
  alerts   none open (pr=33, refs/pull/33/merge, refs/pull/33/head)
  This report's own commit is checked the same way before the run stops.

LEFT OPEN
  - Nothing blocking. For review: how a fault class and a source are
    decided; what counts as an outcome; what the API cannot check of a
    project-token verification (LIMITS) — PR #33's "For review".
  - The protected-ref bypass on push (above).
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
