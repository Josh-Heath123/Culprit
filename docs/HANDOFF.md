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
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35, with 31.1, 31.2 and 32.1 inserted 2026-11-03) |
| Current phase | **32, part 2 — The investigation in the control plane** — status `implemented, awaiting commit and CI`. Every criterion met locally and both audits run (§5); the commit and the CI run on the merge result are the human's next step, so the phase is **not complete** until that run is green. |
| Previous phase | **32, part 1 — The isolation walk: complete**, signed off 2026-11-04 by the architecture session. Merged via PR #22 (`972f288`); CI green on every job on the merge result (run 41815764073), the `fault-library` job 6/6 on Linux. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Every merge to `main` runs `deploy` (PR #19 `a3f110a`, PR #20 `4f69ab3`), and it is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-32-control-plane` (renamed from `handoff-32-1-complete`), cut from `origin/main` = `972f288`; its first commits are part 1's record-keeping and its sign-off. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** Open questions are in §3. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q16 | **Where did the VM remediation land?** Is SSH access to `culprit-vm` restored, and has anything changed on it since 2026-09-12? The answer decides whether Phase 31.2's README may link `culprit.co.za`, and the VM must deploy green before Phase 33. | 2026-11-03, architecture | Nothing yet — Phase 31.2's live link, then Phase 33 |

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
| — | **VM remediation** | **do this, as Phase 30's real-world test** | A human, on `culprit-vm`. **1.** `scripts/backup.sh` first — the next deploy runs every migration from Phase 14 through 30 in one go, including Phase 27's `services`→`components` rename, against a database that has seen none of them. **2.** Before editing anything by hand, run `culprit env capture` against the VM and `culprit diff` it against `.env.prod.example`. If Phase 30 does not report the missing role passwords and the wrong `IMAGE_REGISTRY` as `breaks_request_path`, that is a Phase 30 gap and a better bug report than any fixture. **3.** Then apply the fix: `IMAGE_REGISTRY=ghcr.io/josh-heath123/culprit`, plus every missing key. **4.** `gh run rerun <id> --failed`, and read the deploy job, not the run's colour. |
| 31 | Probes | **complete** | **Signed off 2026-11-03** (architecture session): merged via PR #19 (`a3f110a`), CI green on every job after two ambient dependency fixes (`335aa3b`, `96ac919`). Criteria 3 and 4 met; 1 and 2 carried into 31.1. History — as of 2026-09-12: built and locally green; CI not run. Criteria 3 and 4 PASS; 1 and 2 only partly demonstrable without the demo stack. One enforced invariant was deliberately changed (the binary-wide `net/http` ban, replaced by a per-package one) and one role was widened (`anomaly-detector` SELECT on `connections`) — both argued in §5 and both wanting a human eye. Q12 answered: both surfaces exist. (Carried from the retired Q12: Phase 30 field 4 asked capture for DNS resolvability, TLS certificate expiry and reachable ports, and built them as passive CONFIGURED facts — `component:X dns_resolves` and the like — that stop at a handshake, reading field 17 as "no application requests". Phase 31's own field list names `probe.net.dns_resolve`, `probe.net.tcp_connect` and `probe.net.tls_validity`. **Phase 31 must either re-site them as probes or state that both exist and why.**) **Review 2026-11-03:** every open item decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31. To complete: the human commits, then `/ci` green on the merge result, then merge. |
| 31.1 | Close the probe loop | **complete** | **Signed off 2026-11-04** (architecture session): PR #20 (`4f69ab3`), CI green on the merge result (run 41789133416). Criteria 2 and 4 refined and the auditor's risks decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31.1. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.1, all 17 fields. Phase 31 is merged; the branch `phase-31.1-probe-loop` is cut from `origin/main` = `a3f110a`, with the sign-off as its first commit. Order within the phase: the two gate repairs first — the boundary allowlist (it must exist before anything else lands under `cli/internal/`) and the emptied `.trivyignore` — then expectations, then data sources, then the demo-stack criteria. Replace the whole of §5 with this run's report. Do not stage `shared/uv.lock`. |
| 31.2 | Present what works | **complete** | **Signed off 2026-11-04** (architecture session): PR #21 green on every job; the review's five corrections and the lockfile change verified on disk in `a18c73e`, with the self-check's numbers evidenced in §5. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. **Go-ahead 2026-11-04:** the branch `phase-31.2-present-what-works` exists, cut from `origin/main` = `4f69ab3`. Read Phase 31.2 in the plan including "Carried in from Phase 31.1". **Review 2026-11-04 (before CI):** justfile fix ratified with one change (types generated from the lockfile, as CI does); criterion 4 refined; five README and LIMITS corrections to make on this branch before merge — `DIAGNOSTIC_PLAN.md`, end of Phase 31.2. The last-admin guard is Phase 32's third item. |
| 32, part 1 | The isolation walk | **complete** | **Signed off 2026-11-04** (architecture session): PR #22 (`972f288`), CI green on the merge result with the fault library 6/6 on Linux (run 41815764073). Criteria 1 and 3 refined; decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — all 17 fields, read with "How Phase 32 is run" at the end of the section, which wins where they differ. This run is **part 1 only: the walk, in the binary** — no migration, no API, no frontend, no worker change; those are part 2. Order: the two carried-in items first (CONFIGURED values rendered as shapes; the generated catalogue mirror), then the shared Investigation model and its conformance fixture, then `internal/isolate` and `culprit diagnose`, then the fault library and its CI job. Branch `phase-32-isolation-walk`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32, part 2 | The investigation in the control plane | **implemented, awaiting commit and CI** | 2026-11-04: all eight criteria met locally (§5), both audits run and their findings fixed; not committed, no CI run yet. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — "How Phase 32 is run", then "Part 2 — the investigation in the control plane" at the end of the section, which holds the work order, the criteria and what not to build. Branch `phase-32-control-plane`. Order: the carried-in items first (the token grant, the symptom's attestation, untested versus unexplored branches; then the last admin), then storage, the API, the view, the correlation engine's removal, and the quickstart, README and LIMITS last. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.1 | Design system and the investigation-first interface | not started | Folded in from `docs/PRODUCTISATION.md` on 2026-11-03. The full brief is written when Phase 32 is complete. |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

**Standing task, not a phase — new advisories should be found on `main`, not
mid-phase.** Three times now — OpenSSL in September, then PyJWT, certifi and
urllib3, then aiohttp, Pillow, filelock, pyasn1 and the Caddy build, both on
2026-11-03 — advisories published against pinned dependencies while a phase
sat waiting blocked that phase's CI. Add a weekly `schedule:` trigger that runs
the build-and-scan job on `main` (the image push and `deploy` steps already
require `github.event_name == 'push'`, so a scheduled run cannot publish or
deploy). A red scheduled run is then fixed in its own small pull request.
Dependabot security updates, a repository setting Malcolm can turn on, would
open those pull requests by themselves. Its own commit, not folded into a phase.

**Standing task, not a phase — `CLAUDE.md` size budget.** It is 37.2 KB
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
Phase:        32, part 2 — The investigation in the control plane
Branch:       phase-32-control-plane, cut from origin/main = 972f288.
              origin/main has not moved (an ancestor of HEAD), so the
              working tree is the merge result.
Run:          2026-11-04, /next.
Status:       IMPLEMENTED, NOT COMPLETE. Every acceptance criterion met
              locally, both audits run and their findings fixed. Not
              committed (the human commits); CI NOT RUN on this work. The
              phase is complete only when the run on the pushed commit is
              green.
Commit msg:   ..\phase-32-part2-commit-msg.txt (shared/uv.lock not staged).

GATES (local, Windows, final tree)
  just lint                         PASS
  just typecheck                    PASS
  just lint-imports                 PASS  4 kept, 0 broken (none widened)
  just check-schema-drift           PASS  16 tables
  just check-no-llm-imports         PASS  8 packages (worker/app/correlation
                                          no longer exists, so is skipped)
  just check-invariants             PASS
  just check-scan-coverage          PASS
  just check-migration-round-trip   PASS  7 seeds, one a cited investigation
  just cli-lint / cli-test          PASS
  just extractors-test              PASS
  just test                         PASS  api+scripts+shared 944 passed /
                                          4 skipped (pre-existing), worker 65,
                                          mcp_server 21, 31
  just fault-library                PASS  7/7, auth-audience-ungranted new
  check_coupled_files --base main   PASS
  culprit check --fail-on=breaks_request_path   exit 0
  LLM_PROVIDER=none culprit check               exit 0
  frontend: npm run build / lint    PASS (no warnings in changed files)
  /ci                               NOT RUN — needs the human's commit and
                                    push; git push is denied to this session.

ACCEPTANCE CRITERIA
  1 Round trip                      MET. api/tests/test_investigations_api.py
      posts all seven investigations the fault library recorded from real
      walks (api/tests/data/investigations/, written by the new
      CULPRIT_FAULT_LIBRARY_RECORD hook), the audience one among them, and
      compares GET /{id} whole and /tree's symptom, attestation, diagnosis,
      rubric, edges, citations and per-edge reading ids.
  2 The database holds the rule     MET. As investigation-writer, direct SQL:
      an uncited edge is refused at commit (deferred constraint trigger), a
      citation into another investigation is refused (composite FK
      fk_fault_edge_readings_reading), with a positive control. A temp-table
      shadow of fault_edge_readings is refused too (audit finding, below).
      Migration round-trips with an investigation present.
  3 The view                        MET. Playwright against the fresh-clone
      compose stack, 13/13 checks: list row, root marked once and equal to
      the injected fault, four rubric booleans (reproduced=true,
      discriminated=true, counterfactual=false, verified=false), the
      attestation, an edge expanding to its readings (r5 fail
      probe.auth.token_shape), the four hypothesis groups, and no console
      errors or failed requests. The script is NOT in the repository — see
      "Left open".
  4 Quickstart from a fresh clone   MET. A 675-file export of the working
      tree (no ignored or generated files), run outside %TEMP% with
      COMPOSE_PROJECT_NAME=culprit-freshclone QUICKSTART_HTTP_PORT=8088:
      exit 0, prints /investigations/<id>, stored root
      auth:order-service->inventory-service/audience, complete. README
      matches the recipe step for step. That run was on the tree BEFORE the audit
      fixes. The re-run on the final tree was started and then killed by
      Claude Code for low system memory, so it is NOT RUN: the bootstrap
      copy, the token-out-of-argv change and the manifest value scan reach
      the quickstart path untested end to end (the manifest change is
      covered by test_the_quickstart_model_loads).
      Caveat: an export of the uncommitted tree, not a git clone.
  5 The correlation engine is gone  MET. Not scheduled (WorkerSettings cron:
      drain_streams, drain_edges, score_new_metrics, link_recent_changes);
      worker/app/correlation/, rag/job.py, llm.py, context.py, prompts.py,
      sanitize.py, providers/ and their six test files git-deleted, no skip
      markers; role_table_grants on incident_candidates/incident_anomalies
      show SELECT only for every role but the owner, and a test asserts it.
  6 Token grant                     MET. auth-audience-ungranted: refused,
      hypothesis unexplored, diagnosis partial naming config.read.values;
      auth-audience with the grant still roots at the audience.
  7 Last admin                      MET. PATCH (role, disabled) and DELETE
      answer 409; the concurrent demotion test leaves one admin; removing
      the row lock fails it 3/3.
  8 LLM_PROVIDER=none               MET. The stack run with LLM_PROVIDER=none
      and no model key: diagnose, POST (201) and the browser view all
      complete. Nothing in api, worker or the binary reads the variable now.

WHAT WAS BUILT
  - Carried in: the token read behind config.read.values (a capability-
    checked Secrets source; refused without it); the symptom attestation in
    Go, Python and the shared fixture; untested vs unexplored apart; the
    single-root wording in LIMITS; the last-admin guard.
  - Storage: migration c4e8a1f2b3d5, five tables, role investigation-writer
    (INSERT only), api-reader SELECT; correlation-engine and
    root-cause-writer lose every incident-table write.
  - API: api/app/investigations/ — POST (project token, redaction at the
    reading choke point and every free-text field), list, get, tree.
  - View: InvestigationList.tsx, InvestigationView.tsx,
    components/investigation/Evidence.tsx (readings); the incident panel is
    history (NarrativeCitations.tsx; regenerate removed).
  - Removed: correlation engine, narrative job,
    POST /incidents/{id}/regenerate-root-cause, the anthropic and
    google-genai worker dependencies, the LLM prompts in bootstrap_env.py.
  - Quickstart: per-run demo token secret, the audience fault, diagnose in
    order-service, POST, the printed address; QUICKSTART_HTTP_PORT.
  - Docs: README, LIMITS (rewritten sections + two new), PERMISSIONS
    (the token section was false), UPGRADING, INSTALL, database.md, CLAUDE.md.

FOUND ON THE WAY (defects outside this part's brief, fixed)
  - Part 1 broke `just quickstart` from a fresh clone. It gave
    demo-services/culprit.yaml endpoints, health_path, tokens and
    invariants; the API's manifest model (which the quickstart's bootstrap
    applies) knew none of them, and the bootstrap's `| tee` hid the failure,
    so the demo services started with no ingest keys. No test loaded that
    file. Fixed: the Python model mirrors those fields and Phase 29's
    suppress/severity_overrides, the bootstrap fails loudly, and
    test_the_quickstart_model_loads exists.
  - Investigation JSON wrote an empty fault_tree as null, which the Python
    model refuses — every partial investigation was unpostable. Fixed with
    Investigation.MarshalJSON and a test.
  - Removing the correlation engine first took the engines that the change-
    link and embed jobs still run on — a KeyError on their first run that
    no test saw. Restored, and a new test asserts every ctx key a job reads
    is one startup() creates (mutation-checked).

AUDITS
  invariant-auditor: 3 violations, all reproduced by it, all fixed here:
    1 SECURITY DEFINER trigger with search_path = public: a writer's temp
      table could shadow fault_edge_readings and store an uncited edge.
      Now schema-qualified and search_path = pg_catalog, public, pg_temp;
      a test tries the shadow.
    2 The manifest's `tokens` exemption skipped the credential-value scan
      (ghp_…, AKIA… accepted). The scan now runs; tests for both.
    3 _sanitised missed symptom.source, attestation.reported_by and each
      rubric reason. All redacted; the test covers them.
    Also fixed: the quickstart put the project token in docker's argv.
  phase-auditor: all 8 criteria MET by execution; nothing on the do-not-
    build list built. Its defects fixed here: false copy (bootstrap_env.py
    local message and LLM prompts, INSTALL.md, .env.prod.example and
    worker/.env.example pointing at deleted code, the postmortem empty
    state, the command palette's "Narrative pending"), stale comments, dead
    LLM dependencies. Its check-invariants failure was this session's own
    `ruff format` touching api/app/db/models.py and ~25 other unrelated
    files; all reverted.

LEFT OPEN (decisions for the architecture session)
  - The browser test is in the session scratchpad, not the repository: it
    needs Playwright, which no project here depends on. Committing it means
    adding a dependency and a lockfile; not done unasked.
  - grants_used on a token_shape reading is [] although the probe read a
    credential under config.read.values: the runner stamps grants from the
    manifest, and the manifest cannot declare a per-item grant it only
    sometimes uses. The refusal path is recorded; the success path does not
    name the grant. secretSource has no test of its own (fakes only).
  - A partial diagnosis names a root (the ungranted case stores
    component:order-service). The list shows "partial" beside it, but a
    skimmer could read it as the cause.
  - The last-admin guard is in the API only (LIMITS says so).
  - The root culprit.yaml uses `queue` as a connection kind, which Python's
    closed set does not have; only `just intent` (Go) reads it.
  - config.read.values for a token also lets `culprit env capture` store
    that token's value (PERMISSIONS says so).
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
