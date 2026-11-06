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
| Current phase | **33, part 2 — The agent meets the control plane** — status `in progress`: implemented, every locally runnable criterion passes, both audits run and their findings fixed; **staged, awaiting the human's commit, a pull request and `/ci`** — the end-to-end agent scenario runs only in CI and has not run yet (§5). |
| Previous phase | **33, part 1 — The agent, standing alone: complete**, signed off 2026-11-06 by the architecture session. Merged via PR #27 (`57541e3`); CI green on the merge result, as reported by Malcolm — part 2's first step records the run id. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-33-control-plane`, cut from `origin/main` = `57541e3`; its first commit is the part 1 sign-off. Lands through a pull request. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** §3 is empty. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q17 was ruled at 32.2's review (`DIAGNOSTIC_PLAN.md`, end of Phase 32.2). | | |

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
| 33, part 2 | The agent meets the control plane | **in progress** — staged; local criteria PASS; the CI scenario NOT RUN (§5) | **Brief (2026-11-06):** `DIAGNOSTIC_PLAN.md` Phase 33 — "How Phase 33 is run", then "Part 2" at the end of the section: the work order, defaults, twelve criteria and what not to build. Step 0 records part 1's CI run and regenerates the local `infra/.env.prod` and quickstart volume (the local demo data goes). The signing contract and its conformance fixture come before anything that uses them. Backend and binary only — no frontend change. Branch `phase-33-control-plane`. Lands through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 33, part 3 | The operator's surface | not started | Criteria written at part 2's review. Now also holds the dashboard control that opens an investigation through an agent (moved from part 2, 2026-11-06). |
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
Phase:        33, part 2 — the agent meets the control plane
Branch:       phase-33-control-plane, cut from origin/main = 57541e3; d403259
              is the part 1 sign-off. The work is STAGED, not committed:
              message ..\phase-33-2-control-plane.txt. shared/uv.lock not
              staged. Lands through a pull request.
Run:          2026-11-06, /next.
Status:       IMPLEMENTED, NOT COMPLETE. Every criterion that can run
              without the CI scenario passes locally, executed by the tests
              and by phase-auditor. NOT RUN anywhere yet: the end-to-end
              agent scenario (criteria 8's first clause, 9's topology, 10),
              which runs only in CI's e2e job (`just agent-e2e`) — its one
              local attempt was stopped by the system for low memory before
              it began. Needs: the human's commit, push and pull request,
              then /ci.

STEP 0 — THE RECORD, AND THE LOCAL ENV
  Part 1's CI: PR #27's pull_request run 42176958562 on the merge ref,
  success on every job — "Agent image checks" among the cli build's steps,
  on Linux — deploy and publish skipped; the push run on main for 57541e3,
  42177585117, success. Part 1's criterion 7 ("checked in CI") is met.
  The local infra/.env.prod regeneration and quickstart volume recreation:
  NOT DONE. Moving the file aside and removing the volume were both refused
  by the permission system; they are Malcolm's to run (the commands are in
  this report's LEFT OPEN). Nothing in this part needed them before CI.

STEP 1 — CARRIED IN
  api/tests/data/investigations/ re-recorded by the fault library under
  config.inspect.values (token_shape v3, grants_used named, no
  config.read.values left); the browser assertion follows; UPGRADING has the
  rename. NOT DONE: the README's partial screenshot and its alt text — no
  stack could run here. CI's e2e job takes that screenshot from the
  re-recorded data; copy docs/screenshots/investigation-partial-1280.png
  from that run's e2e-screenshots artifact, and fix README.md:63.

GATES (local, Windows, staged tree)
  just lint / typecheck / lint-imports         PASS (4 contracts kept)
  just check-schema-drift / no-llm-imports     PASS
  just check-invariants / check-scan-coverage  PASS
  just check-frontend-tokens                   PASS
  just cli-lint / cli-build                    PASS
  go test ./... (cli)                          PASS
  just test                                    PASS  api+scripts+shared 1137 / 4 skipped,
                                                     worker 65, mcp 21, extractors 31
  frontend tsc -b, npm test                    PASS
  just check-migration-round-trip              PASS  (agents, a task, a nonce and an
                                                     audit row seeded)
  culprit check / LLM_PROVIDER=none            exit 0 / 0
  just agent-e2e                               NOT RUN (CI-only; see Status)
  /ci                                          NOT RUN — needs the commit and a PR

CRITERIA (part 2)
  1  signing fixture, Go and Python                       PASS. 14 cases, each
       as written in both; each language reproduces the fixture's signatures
       byte for byte from the seeds.
  2  pairing code once, not after expiry; no private key
     in any byte sent while pairing                       PASS. API tests;
       the fake control plane dumps every request (httputil.DumpRequest)
       until the agent is paired — exactly one — and none holds the seed or
       key in seven encodings.
  3  revocation refuses the next request; allowance
     removal on the next task; no restart                 PASS (API and binary).
  4  allowance naming an unreported grant, a wildcard or
     `all` → 422; the chaos test over the real transport  PASS. 422s in the
       API; the chaos case runs the real internal/transport client over HTTP
       against a control plane that verifies signatures with agentauth: the
       task is refused, recorded, allowance_ignored names the grant, and the
       shipped chain equals the local log byte for byte. Not repeated
       against the real API (the API 422s such an allowance; the case arises
       only when a configuration shrinks after pairing).
  5  POST /readings: an agent's credential only           PASS. Project token
       401, none 401, signed 201, another agent named 403.
  6  every route and its credentials                      PASS. The test reads
       the app's dependency tree; the project token is on exactly the three
       capture routes and POST /investigations. Mutation-tested four ways
       (phase-auditor), and a hidden wrapper calling require_project_token
       is now caught by a source scan (mutation-tested).
  7  investigations record who submitted them             PASS.
  8  one agent_audit_log row per probe in the CI
     scenario; chain extension refused; no role can
     update or delete, shown red without the trigger      Chain and trigger
       PASS (dropping the trigger turns UPDATE and DELETE red; TRUNCATE has
       its own); the CI clause NOT RUN — now one-to-one per task.
  9  no shared Compose network in CI; no listen call;
     transport dials only its address, no redirect, the
     allowlist's third package, mutation-tested           Local PASS (each
       mutation caught: allowlist, Listen, dialer, redirect, proxy). CI
       topology NOT RUN. Defect found by the phase audit and fixed: the
       quickstart's Caddy answered only `localhost`, so the agent's requests
       as host.docker.internal matched no site (shown live) — the local
       DOMAIN now names both (Caddy adapt checked; test added).
  10 reachability completes; schema partial naming
     db.metadata.read; audience roots at the audience     NOT RUN (CI-only).
       Reasoned through the walk by the auditor: each would assert as
       written. The "schema" walk is the latency fault over the demo model
       plus an orders-db, whose edge only db.metadata.read can test.
  11 migration round-trips with agents, tasks, audit rows PASS.
  12 LLM_PROVIDER=none changes nothing                    PASS.

WHAT WAS BUILT
  - Signing: cli/internal/agentauth, api/app/agents/signing.py,
    shared/tests/agent_signing_conformance.json.
  - Storage: d7a3e5f1b9c2 — six tables; agent-admin, agent-registrar,
    agent-gateway; append-only and chain-extension triggers;
    investigations.submitted_by; role secrets threaded everywhere.
  - API: api/app/agents (pairing codes, register, list, allowances,
    revoke, tasks, a task, the audit log; claim, result, audit head and
    append for the agent); require_agent and require_project_token_or_agent;
    POST /readings agent-only; POST /investigations records its submitter.
  - Binary: cli/internal/transport; agent config control_plane and key;
    `culprit agent init`, `pair` (`--code -` reads stdin); the transport
    as the agent's task source, shipping its audit chain before results.
  - CI: `just agent-e2e`, a step in the e2e job; the fault stack's
    order-service gets host.docker.internal; the quickstart answers it.
  - Docs: PERMISSIONS, UPGRADING, LIMITS, PROBES, ARCHITECTURE, the
    database and determinism rules, CLAUDE.md.

DELIBERATELY NOT BUILT (part 2's Do-NOT)
  No frontend change beyond the one re-recorded assertion; no deployment
  recipe beyond the CI topology; no docs/SECURITY.md; no mutual TLS; no
  write capability; no multi-tenancy; no hosted deployment; no
  POST /investigations/{id}/probe.

AUDITS
  invariant-auditor: one violation, fixed — agent-admin held SELECT on
    the pairing codes it never reads (now INSERT only, with no RETURNING;
    the sequence USAGE it named as unneeded IS needed — Postgres checks it
    for an identity default, shown by the tests — and is argued in the
    migration). One security defect, fixed — a nonce could be deleted while
    its request was still fresh (a replay window of up to a second at the
    edge of future skew); now kept 2 x 300 + 60 s, with a test that replays
    such a request after cleanup (mutation-tested). Risks fixed: a transient
    DB error on an audit insert reported as a broken chain; the determinism
    rule and ARCHITECTURE naming two network packages, not three; the
    pairing code in shell history (`--code -`). Risks documented in LIMITS:
    http allowed for control_plane.url; what a leaked agent DB credential
    could do; a malformed body's 422 before the 401. api-reader's SELECT on
    the four new tables argued in the migration, as c4e8a1f2b3d5's was.
  phase-auditor: every local criterion PASS; defects fixed — the Caddy
    host (above), the scan gap in criterion 6, and three checks weaker than
    the wording (aggregate audit counts, networks compared only with "api"
    containers, pairing capture limited to one path).

PLAN NOTES
  - Criterion 10's "schema investigation": the demo model has no database,
    so the scenario adds one (orders-db) to the agent's own copy of the
    model; adding it to demo-services/culprit.yaml would have turned the
    fault library's audience walk partial.
  - The project token's narrower scope breaks any CI that posts readings
    with it (UPGRADING says so).

LEFT OPEN
  - Commit, push, pull request, /ci — the scenario's first run.
  - Malcolm's local env, as 32.2's review required:
      mv infra/.env.prod infra/.env.prod.pre-33-2
      docker volume rm culprit-quickstart_quickstart-postgres-data culprit-quickstart_quickstart-redis-data
      just quickstart
    Also removable: volumes culprit-qs-322_*, culprit-qs-322b_*,
    culprit-qs-332_*.
  - The README partial screenshot and README.md:63, from CI's artifact.
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
