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
- **Both read the whole file first.**

**CI is part of the gate set.** A phase is not complete until CI is green on the
**merge result** — `origin/main` merged into the branch — not on the branch
alone. Local `/verify` covers neither: it runs a subset of the checks, on a tree
that is not what gets merged, on Windows rather than Linux. Run `/ci` before
reporting any phase complete.

**Committing — the human does it.** Claude Code stages the work and writes the
message to a file, then stops and prints the one command for the human to run.
Do not attempt `git commit` yourself; it has been denied five runs running and
the cause is the interactive decision, not the ruleset.

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35, with 31.1, 31.2, 32.1 and 32.2 inserted) |
| Current phase | **32.2 — Close-out** — status `complete`, awaiting the architecture session's sign-off. On `main` as `2e05980` + `2e187fc` (pushed to `main` directly, without a pull request). CI/CD on `main` green on every job, `deploy` skipped (run 42083753833); the scheduled scan started by hand once, green, publishing nothing (run 42084489435). §5. |
| Previous phase | **32.1 — Design system and the investigation-first interface: complete** (parts 1 and 2), signed off 2026-11-05 by the architecture session, subject to PR #25's final run (on `e97189f`, the bootstrap fix) being recorded green — Phase 32.2's first step. Merged via PR #24 (`5a7acfe`) and PR #25 (`072fb4f`). Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-32.2-close-out`, cut from `origin/main` = `072fb4f`; its first commit is this sign-off. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** Q17 (machine vocabulary in the walk's text) is open in §3 and does not block. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q17 | **How much machine vocabulary may the walk's text keep?** Phase 32.2 removed every phase number and raw hypothesis kind (the criterion, tested in Go on every simulated and real walk) and describes subjects in words. Work order item 5 also says "no … machine phrasing", and what a user still reads includes probe ids (`probe.auth.token_shape was refused`), grant names (`needs config.read.values for order-service/INVENTORY_TOKEN`), hypothesis and reading ids in rubric reasons (`(h2, h4, h5)`, `(r5, then r7)`), and an arrow pair in a placement reason (`order-service -> inventory-service`). Each is precise, and the interface shows the same ids beside the readings they name, so Claude Code kept them — but that is a ruling, not a fact. Accept them as vocabulary, or name which to replace (a later brief). | 2026-11-05, Phase 32.2 phase audit | Nothing |

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
| 32.2 | Close-out | **complete** — `2e05980`, `2e187fc` on `main`; run 42083753833 green, `deploy` skipped; Images run 42084489435 green (§5) | **Brief (2026-11-05):** `DIAGNOSTIC_PLAN.md` Phase 32.2 — its work order, criteria and what not to do. Two commits: line endings alone first (message `..\phase-32.2-1-line-endings.txt`; stage it and stop for the human to commit), then everything else (`..\phase-32.2-2-close-out.txt`). Record PR #25's final run first. Branch `phase-32.2-close-out`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

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
Phase:        32.2 — Close-out
Branch:       phase-32.2-close-out, cut from origin/main = 072fb4f; 2aadd71
              (the sign-off), 2e05980 (commit 1) and 2e187fc (commit 2),
              both committed by the human. Both reached main by a direct
              push, not a pull request, so main = 2e187fc = the merge
              result. shared/uv.lock not staged.
Run:          2026-11-05, /next.
Status:       COMPLETE. Every criterion met, CI green on the merge
              result (main itself), the scheduled scan started by hand
              once and green. Q17 (§3) is open and does not block.

STEP 1 — THE RECORD
  PR #25's final run, on e97189f (the bootstrap fix): run 41919870968,
  pull_request, conclusion success on every job — lint, typecheck, cli,
  test, migration-round-trip, self-check, kind-capture, fault-library,
  e2e, build x5; deploy skipped. Phase 32.1 part 2's sign-off condition
  is met. (The push run on main after the merge, 41979307020, was green
  on every job but deploy, which failed against the offline VM — the
  failure this phase removes.)

GATES (local, Windows, final staged tree)
  just lint / typecheck / lint-imports         PASS (4 contracts kept)
  just check-schema-drift / no-llm-imports     PASS
  just check-invariants / check-scan-coverage  PASS
  just check-frontend-tokens                   PASS
  just cli-lint / cli-build                    PASS
  just test                                    PASS  api+scripts+shared 1080 / 4 skipped
                                                     (pre-existing), worker 65, mcp 21,
                                                     extractors 31, Go all ok
  frontend tsc -b, oxlint, npm test            PASS  (npm test 14/14; oxlint 0 errors,
                                                     2 pre-existing warnings: ui/badge,
                                                     ui/button only-export-components)
  npm audit --audit-level=high                 PASS
  check_coupled_files --base origin/main       PASS
  culprit check --fail-on=breaks_request_path / LLM_PROVIDER=none   exit 0 / 0
  just fault-library                           PASS 7/7 (twice: once recording, once
                                                     by the phase auditor)
  just e2e (fresh quickstart, see below)       PASS 16/16
  After commit 1 alone, the same set was run: all PASS.
  /ci                                          GREEN — see CI below

CRITERIA
  PR #25's final run recorded green, e2e included      MET (above).
  Line-endings commit empty under --ignore-space-at-eol, gates green
    after it                                           MET. 2aadd71..2e05980 is
      .gitattributes alone. `git add --renormalize .` changed nothing: the
      index already held every text file as LF (0 i/crlf, 0 i/mixed). THE
      BRIEF WAS WRONG IN ONE RESPECT: it expected hundreds of files; the
      churn CLAUDE.md warned of existed only in Windows working copies
      (core.autocrlf=true), which `eol=lf` now overrides. Gates green
      after it locally; in CI with commit 2.
  CLAUDE.md under 8 KB, contradicting nothing in §1     MET. 5,221 bytes (was
      53,246 in the index — it had grown past the 37 KB the standing task
      quoted). The architecture walkthrough and the CI/Docker traps moved
      word for word to docs/ARCHITECTURE.md, annotated where the pipeline
      changed. Rules stay in .claude/rules/.
  deploy skipped rather than failed on the merge         MET. The push run on
      main for 2e187fc (42083753833): deploy skipped, every other job
      success — where 072fb4f's push run failed on deploy.
  Scheduled workflow started by hand once, result in §5  MET. `gh workflow
      run images.yml --ref main` -> run 42084489435, workflow_dispatch on
      2e187fc: build x5 success (every image built and Trivy-clean),
      publish skipped — it published nothing, as designed.
  No phase number or raw kind in the walk's user text;   MET.
    one label map; a missing label fails in both
    languages; fault library 7/7, same roots
      - one source: hypothesis_labels in investigation_conformance.json;
        Go (model.HypothesisLabels) and frontend (lib/hypotheses.ts) copies
        are held to it exactly by a test each; Python checks the kind set.
        The phase auditor showed it with scratch copies: a kind added to
        the fixture fails Go and 2 node tests; a kind added to Go alone
        fails internal/model and internal/isolate.
      - every isolate test walk, and every fault-library walk, asserts no
        phase number and no raw kind in the statement, the fix, each
        hypothesis reason and each rubric reason. Mutation-tested: putting
        "Phase 34" back fails 17 assertions; putting the raw-kind clause
        back fails 3 tests.
      - the 8 re-recorded investigations, stripped of prose, ids and
        timestamps, are identical to their predecessors (root, complete,
        rubric, hypothesis statuses, tree, verdicts): wording changed,
        verdicts did not.
  One broken route fails only its own browser test       MET, locally. Against
      a fresh quickstart: 16 passed. With SettingsServices made to throw
      and the frontend rebuilt: 1 failed ("settings: services"), 15 passed
      — every tour test after it included. Reverted.
  Nothing references docs/review/                        MET. Removed (history
      at 072fb4f) and added to .gitignore; remaining mentions are the
      plan's own description of the removal and this handoff's history.

WHAT WAS BUILT
  - The walk's words: cli/internal/isolate/describe.go (kindPhrase,
    describe, couldNotCheck); isolate.go's statements and rubric reasons
    rewritten ("order-service fails because of the token audience
    order-service presents to inventory-service: a probe of it fails, and
    every other explanation the walk could test was ruled out by a
    reading"; verified: "no fix has been applied and checked: Culprit
    cannot yet re-run an investigation after a change"); one placement
    reason in cmd/culprit/diagnose.go.
  - Recordings: the 7 fault-library investigations re-recorded from real
    walks; partial-with-boundary from its simulated world, whose
    environment, agent and reporter now say "simulated" (was "test").
  - Pipeline: .github/workflows/images.yml (workflow_call + weekly
    schedule, Mondays 04:17 UTC + workflow_dispatch). Build-and-scan holds
    a read-only token; a separate publish job (packages: write) pushes the
    exact scanned images (saved as an artifact, never rebuilt), only when
    the caller passes publish. ci-cd.yml: deploy only on workflow_dispatch
    from main with "deploy" ticked; such a run publishes its own commit
    first, so the VM never pulls an older :latest.
  - Go 1.27 in cli/go.mod (CI's version); README and LIMITS follow.
  - Browser tour: one test per route on a worker-scoped signed-in page;
    the guard detaches its listeners per test; the member is created in
    global setup; a failure screenshot of the shared page.
  - README screenshots regenerated from a fresh quickstart (the list shows
    "simulated"; the complete view shows the new statement). The list
    shows two complete quickstart runs because the quickstart ran twice
    (port 80 is held on this machine by WSL's Apache — LIMITS).
  - CLAUDE.md rewritten; docs/ARCHITECTURE.md; stale pointers to its old
    sections repointed (LIMITS, examples/, mcp_server, worker comments,
    a scripts test, deploy.sh, the docker-compose.prod.yml header).
  - LIMITS: no hosted instance and manual deploy; the weekly scan's
    up-to-a-week lag; the tour's extra sign-in per failing test; stored
    investigations keep their old wording; the Go floor. INSTALL and
    UPGRADING describe the manual deploy. PERMISSIONS says nothing about
    deploy behaviour, so it needed no change.
  - The SARIF informationUri pointed at the offline culprit.co.za; it now
    names the GitHub repository.

DELIBERATELY NOT DONE
  No feature work, nothing from Phase 33, no change to what the walk
  decides (verified field by field above). Probe ids, grant names and
  reading/hypothesis ids in the walk's text kept — Q17.

AUDITS
  invariant-auditor: CLEAN, 0 violations. Risks fixed: a hand-started
    deploy could ship new deploy files against an older :latest (it now
    publishes first); the weekly scan held packages: write (now split);
    kindPhrase("") would panic (guarded, tested); the two readability
    checks used different patterns (one regex now). Risks left: no lint
    covers hand-built subjects in Go (test inputs only today); Python
    holds the kind set, not a label copy (it renders no labels).
  phase-auditor: every pre-merge criterion it could execute PASS; the
    hand-started scheduled run NOT RUN (cannot be, before the merge); CI
    NOT RUN. Defects fixed: ARCHITECTURE.md and docker-compose.prod.yml
    still described deploy-on-push; six stale CLAUDE.md section pointers;
    the SARIF URL. Raised for a ruling: Q17.

HOW THE LOCAL BROWSER RUN WAS MADE (and what it left)
  The local infra/.env.prod predates the fact-, capture-, probe- and
  investigation-writer roles, so neither a fresh nor the existing
  quickstart database could be migrated with it. Reading or regenerating
  it was declined, rightly — it is Malcolm's. Instead a throwaway git
  worktree (no .env.prod, so its quickstart generated its own) ran under
  COMPOSE_PROJECT_NAME=culprit-qs-322b on port 8088. The worktree and its
  env are deleted; the stacks are down. Left behind, for Malcolm to remove
  if wanted: Docker volumes culprit-qs-322_* and culprit-qs-322b_*. The
  local infra/.env.prod still lacks those keys, so `just quickstart` in
  this checkout fails in migration until it is regenerated
  (scripts/bootstrap_env.py --local --force, which rotates every secret;
  the old culprit-quickstart database volume would then need recreating).

CI (/ci)
  commit   2e187fc7e2bb366425a5d3b65275f5be83fbb315
  run      42083753833  https://github.com/Josh-Heath123/Culprit/actions/runs/42083753833
  Merge result: main was pushed to 2e187fc directly, so the run on main
  IS the merge result (no pull request run exists for this phase).
  Jobs: success lint, typecheck, cli, test, migration-round-trip,
    self-check, kind-capture, fault-library, e2e (the per-route tour, on
    Linux), build x5 (images.yml through workflow_call), publish x5 (the
    new job: :sha and :latest pushed from the scanned images); skipped
    deploy.
  Verdict: GREEN.
  Images, by hand: run 42084489435
    https://github.com/Josh-Heath123/Culprit/actions/runs/42084489435
    workflow_dispatch on main, 2e187fc: build x5 success, publish
    skipped. Verdict: GREEN. The weekly schedule (Mondays 04:17 UTC) is
    now registered.

LEFT OPEN
  - Q17 (§3).
  - Both commits went to main without a pull request, past the "Protect
    Main" ruleset (its `update` rule): no pull_request run, no review
    surface. The push run above is the gate that ran. Whether that is how
    phases should land is Malcolm's to say.
  - This report's own update (recording the two runs) is uncommitted;
    message ..\phase-32.2-3-record.txt.
  - actionlint could not be run (fetching it was refused); CI's own
    workflow parsing is the check.
  - The e2e job still rebuilds every image (accepted, Phase 32.1 review).
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
