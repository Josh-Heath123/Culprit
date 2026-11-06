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
  run. The human pushes the branch, opens the pull request, and merges it when
  every check is green.
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
| Current phase | **33, part 1 — The agent, standing alone** — status `in progress`: implemented, every part-1 criterion passes locally, both audits run; **staged, awaiting the human's commit**, then a pull request and `/ci` (criterion 7 is checked in CI). §5. |
| Previous phase | **32.2 — Close-out: complete**, signed off 2026-11-05 by the architecture session. On `main` as `2e05980` + `2e187fc` by a direct push (run 42083753833 green, `deploy` skipped); its record commit `7130927` and this sign-off land by pull request. Decisions at the end of Phase 32.2 in `DIAGNOSTIC_PLAN.md`; Q17 ruled there. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-33-agent`, cut from `origin/main` = `71c1b3b` (PR #26 merged; its push run 42090677582 green, `deploy` skipped). Do not stage `shared/uv.lock`. |
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
| 33, part 1 | The agent, standing alone | **in progress** — staged, local criteria all PASS, awaiting commit, PR and CI (§5) | **Brief (2026-11-05):** `DIAGNOSTIC_PLAN.md` Phase 33 — all 17 fields and the three "Added" notes, read with "How Phase 33 is run" at the end of the section, which wins where they differ; then "Part 1" there for the work order, the criteria and what not to build. The carried-in items come first. Branch `phase-33-agent`, cut from `origin/main` once the pull request carrying 32.2's record and this sign-off has merged. It lands on `main` through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 33, part 2 | The agent meets the control plane | not started | Criteria written at part 1's review. Before it runs, the local `infra/.env.prod` is regenerated and the local quickstart volume recreated (32.2 review). |
| 33, part 3 | The operator's surface | not started | Criteria written at part 2's review. |
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
Phase:        33, part 1 — the agent, standing alone
Branch:       phase-33-agent, cut from origin/main = 71c1b3b (PR #26's merge,
              carrying 32.2's record and the sign-off). Its push run on main,
              42090677582, was green on every job, deploy skipped. Nothing
              committed: the work is STAGED; message ..\phase-33-1-agent.txt.
              shared/uv.lock not staged.
Run:          2026-11-05, /next.
Status:       IMPLEMENTED, NOT COMPLETE. Every part-1 criterion PASSES
              locally, executed by the phase auditor as well as the tests.
              Needs: the human's commit, the branch pushed and a pull
              request opened (handoff protocol), and CI green on its merge
              result — criterion 7 says "checked in CI", and only CI runs
              the image check on a classic Docker daemon, on Linux.

GATES (local, Windows, staged tree)
  just lint / typecheck / lint-imports         PASS
  just check-schema-drift / no-llm-imports     PASS (no-llm: 8 packages, cli included)
  just check-invariants / check-scan-coverage  PASS
  just check-frontend-tokens                   PASS
  just cli-lint / cli-build / cli-test         PASS (go test ./...: 13 packages)
  just test                                    PASS  api 1080 / 4 skipped (pre-existing),
                                                     worker, mcp, Go
  just extractors-test                         PASS
  shared + scripts tests                       PASS  755 / 4 skipped
  frontend tsc -b, npm test                    PASS
  check_coupled_files --base origin/main       PASS (nothing committed yet; vacuous)
  culprit check / LLM_PROVIDER=none            exit 0 / 0
  TestTheNetworkBoundaryIsAnAllowlist          PASS — internal/agent links no net,
                                                     net/http or crypto/tls
  just fault-library                           PASS 7/7 (twice: once by this run, once by
                                                     the phase auditor), with the wording
                                                     check now refusing "->"
  scripts/check_agent_image.sh                 PASS locally (Docker Desktop)
  /ci                                          NOT RUN — needs the commit and a pull request

PART 1 CRITERIA
  1 token_shape names config.inspect.values in grants_used; a refused
    reading names no grant; secretSource has tests of its own   PASS.
      secret_source_test.go drives the real source over the process
      adapter (5 tests) and the runner (3). On real walks: the
      auth-audience reading is `fail ['config.inspect.values'] v3`; the
      ungranted one `refused`, no grants_used. Mutation: an empty
      exercised list fails 2 tests.
  2 only config.read.values -> token_shape refused; only
    config.inspect.values -> env capture stores no value         PASS.
      Unit test, and the auditor on the real binary: a planted value
      granted only config.inspect.values is absent from the payload; the
      control run with config.read.values has it.
  3 parser refuses a wildcard, `all`, an unknown grant, each with its
    line                                                          PASS.
      9 subtests (net.*, "*", all, a typo, `all`/`*` as value or item,
      *.write, true for a per-item grant); the binary prints file:line.
  4 an ungranted task is refused without dialling, and recorded  PASS.
      Counting fake network: 0 dials; a refused reading; audit entries
      probe(refused, grants []) then task(refused). An allowance naming the
      missing grant changes nothing and lands in allowance_ignored.
  5 a removed grant takes effect on the next task, no restart    PASS.
      Test, and the auditor with one long-lived process: granted, then
      the file rewritten, then refused, same PID.
  6 one audit entry per executed probe; an edit or deletion is
    caught by the chain check                                     PASS.
      A real walk: readings and probe entries match one to one, grants
      included. Edited line, deleted line, renumbered successor and
      reordering each named by line; the agent will not start on a
      broken log.
  7 image under 30 MB, non-root, read-only root fs, checked in CI
                                                       PASS locally; CI NOT RUN.
      distroless/static nonroot (uid 65532); binary layer 12.7 MB, about
      13 MB in all (Docker Desktop's containerd store reports 5.5 MB
      compressed; CI's classic store reports uncompressed, the stricter
      figure). The agent ran --read-only --network none, refused the
      ungranted task, completed the granted one, chain intact. Step
      "Agent image checks" in images.yml runs it for the cli image.
  8 no arrow pair in the walk's text, in 32.2's wording test     PASS.
      assertReadable and the fault library's check refuse "->"; the one
      sentence that had one ("for %s -> %s") now says "from ... to ...".

WHAT WAS BUILT
  - config.inspect.values: Go capability, the shared Python enum and the
    conformance fixture; secretSource requires it per key and
    config.read.values no longer satisfies it; capture never stores under
    it. token_shape -> version 3; catalogue mirror regenerated; the fault
    environments and quickstart (demo-services/culprit.yaml) and the fault
    library's expectation renamed; PERMISSIONS, PROBES, LIMITS.
  - grants_used = declared ∪ exercised: capability.WithExercised /
    RecordExercised; sources record after the ledger allows and (for a
    secret) after the value was read; the runner keeps only names the
    ledger holds, so no probe can widen a reading's claim.
  - cli/internal/agent: config (line-numbered refusals, re-read every
    task), Task/Result, the hash-chained audit log and verify, DirSource
    (id = file name, no reuse, nothing overwritten), the loop; an agent
    that cannot write its audit stops. capability.Grants.Narrow.
  - cli/cmd/culprit/agent.go: `culprit agent` (--config, --tasks, --audit,
    --once, --poll) and `culprit agent verify` (0 intact, 1 broken, 2
    unreadable); the executor runs probe tasks and walks under the agent's
    grants only, through probeRunnerUnder/walkRunnerUnder (diagnose.go
    refactored; `culprit diagnose` unchanged). Plugins are never run by
    the agent.
  - scripts/check_agent_image.sh and its CI step; cli/Dockerfile comment.

DELIBERATELY NOT BUILT (part 1's Do-NOT)
  No transport, no control-plane client, no migration, no api/ worker/ or
  frontend change beyond the catalogue mirror and the shared grant list,
  no deployment recipe beyond the image, no write capability.

AUDITS
  invariant-auditor: CLEAN, 0 violations. Defect fixed: the image check
    would have failed on a Linux runner (the agent's 0700/0600 output,
    unreadable by the runner's user; Docker Desktop hid it) — it now runs
    as the host user, after the non-root check on the image's own user.
    Risks fixed: grants_used filtered through the ledger; inspect recorded
    only after a read; task id must equal file name, ids not reused,
    results never overwritten; LIMITS now says the chain is
    tamper-evident, not tamper-proof (anyone with write access can
    rewrite it consistently) and that two agents must not share a log;
    a stale secret-reader comment. Risks left: process.exec.allowlist is
    recorded when authorised, not after the command succeeded; the size
    check is daemon-dependent (CI's is the stricter).
  phase-auditor: all eight criteria PASS locally, criterion 7's CI half
    NOT RUN. Defects fixed: `agent verify` on an unreadable log exited 1
    (now 2); a YAML syntax error named no line (now does, without quoting
    the file); ARCHITECTURE.md's token sentence.

PLAN NOTES
  - Field 14's "an agent with only net.* and config.read.names" writes a
    wildcard the part-1 parser (rightly) refuses; read it as the net.*
    capabilities listed by name.
  - The recorded investigations in api/tests/data/investigations/ and
    frontend/e2e/investigations.spec.ts:101 still say config.read.values,
    and auth-audience.json records token_shape v2 with no grants_used —
    stale, not just old wording. Part 1 may not change api/ or the
    frontend, and nothing fails because of them; part 2 should re-record
    them (CULPRIT_FAULT_LIBRARY_RECORD) and update the e2e assertion, and
    the README's partial screenshot with them.
  - A user's culprit.yaml that granted config.read.values for a token
    now has the audience hypothesis refused until renamed (LIMITS).

LEFT OPEN
  - Commit, push, pull request, /ci.
  - The re-recording above (part 2).
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
