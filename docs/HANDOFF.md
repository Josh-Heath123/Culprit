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
| Current phase | **35, part 1 — The agent surface** — status `gates red` (ambient): implemented, every local gate and every CI job green except `e2e`, which failed three times installing `just` from apt because the runner could not resolve Ubuntu's mirrors — no e2e test ran. PR #34, not merged. Q24. Report in §5. |
| Previous phase | **34 — The verification loop and calibration: complete** (two parts), part 2 signed off 2026-11-11 by the architecture session. Merged via PR #33 (`0effc53`), every pull-request check green. Decisions at the end of Phase 34 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-35-mcp`, cut from `origin/main` = `0effc53`; its first commit is the Phase 34 sign-off. Lands through a pull request. Do not stage `shared/uv.lock`. |
| Blocking questions | **Q24** blocks PR #34's merge gate (CI's `e2e` cannot install `just`), not the design. Q22 and Q23 are for review. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q22 | Phase 35 part 1, criterion 3 — "every tool's response validates against the same model the CLI's JSON uses" — cannot hold literally for `culprit_system_model` and `culprit_explain_connection`, which have no CLI command. Built: every record inside them is a model record that validates (facts, check's own divergence objects, built subjects, catalogue manifests); their envelopes are new. Accept that reading, or ask for the envelopes published as each tool's `outputSchema`? | 2026-11-11, Phase 35 part 1 | No |
| Q23 | A probe's `url`/`host`/`port` inputs are not bound to the endpoints `culprit.yaml` declares — true of `culprit probe` since Phase 31, and now reachable by a coding agent through `culprit_probe` (the phase-auditor sent a GET to an arbitrary local address under `net.http.outbound`). Documented in LIMITS ("A granted probe goes where its inputs say"). Bind `culprit_probe`'s inputs to declared endpoints, or accept the limit? | 2026-11-11, Phase 35 part 1 | No |
| Q24 | CI's `e2e` job installs `just` with `apt-get` (ci-cd.yml:513). On PR #34 (run 43045419342) it failed three times, 15:12–15:40 UTC, resolving Ubuntu's mirrors, before any test ran; every other job passed. Re-run it once the runners' DNS recovers, or install `just` another way (its GitHub release with a pinned checksum; the workflow comment at :511 records that a third-party action was avoided on purpose)? Claude Code has not changed the workflow. | 2026-11-11, Phase 35 part 1 | PR #34's merge gate |

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
| 35, part 1 | The agent surface | **gates red** (ambient: CI `e2e` could not install `just`; Q24) — PR #34, not merged | **Brief (2026-11-11):** `DIAGNOSTIC_PLAN.md` Phase 35 — all 17 fields, read with "How Phase 35 is run" at the end of the section, which wins where they differ; then "Part 1" there for the work order, five criteria and what not to build. `culprit mcp` is served by the binary over stdio; the Python MCP server is not repointed. Branch `phase-35-mcp`. Lands through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
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
Phase:        35, part 1 — the agent surface
Branch:       phase-35-mcp, from origin/main = 0effc53 (PR #33's merge); its
              first commit is the Phase 34 sign-off (eb09d15).
Run:          2026-11-11, /next.
Status:       IMPLEMENTED; every local gate green; the fault library 13/13
              locally with Docker; both audits clean, their findings fixed.
              CI: NOT GREEN — every job but e2e passed on
              PR #34; e2e failed three times installing `just` from apt
              (runner DNS), before any test ran. Status gates red (ambient).

WHAT WAS BUILT (work order 1-4)
  1 `culprit mcp` (cli/cmd/culprit/mcp.go): MCP over stdin and stdout from
    the binary, six read-only tools — culprit_system_model, culprit_check,
    culprit_explain_connection, culprit_probe, culprit_diagnose,
    culprit_verify. cli/internal/mcp is the protocol and nothing else:
    newline-delimited JSON-RPC 2.0; initialize (2025-06-18, 2025-03-26,
    2024-11-05), tools/list, tools/call, ping; notifications unanswered.
    It links no Culprit package and no network package. Every tool's
    arguments are a closed schema (additionalProperties false), checked
    before the handler runs, so an argument naming a grant is a protocol
    error. The vantage (--from), the state directory, the agent id and the
    timeouts are the server's flags, never arguments.
    To call the same code as the commands, the bodies of `culprit
    diagnose`, `verify` and `probe` were lifted into runDiagnose, runVerify
    and runProbe, which the commands and the tools both call; check.Run
    was already a function. No second implementation of anything.
  2 Each answer is the command's --format json: culprit_check is `culprit
    check --format json`; culprit_probe is `culprit probe --format json`
    ({readings, refused}); culprit_diagnose is {investigation, verify} —
    the investigation `culprit diagnose --format json` prints, and the
    culprit_verify call to make with the four change kinds and what each
    explains; culprit_verify is the Verification. The text content is the
    same JSON. No prose field anywhere.
  3 A scripted MCP client (mcp_test.go, mcpClient) drives the server over
    a pair of streams: in-process through the real cobra command, and in
    the fault library through the real linux binary, `docker exec -i
    <vantage> culprit mcp`, over its stdin and stdout: subtests
    mcp/auth-audience (fix applied -> verified) and mcp/wrong-fix (token
    re-minted for the wrong audience -> not_resolved, reason naming
    probe.auth.token_shape). Neither is counted in results.json.
  4 README ("For a coding agent: culprit mcp": the mcpServers snippet, the
    tool table, what it cannot do; a Key-features row; project structure;
    future work now part 2), LIMITS ("The agent surface", nine entries),
    ARCHITECTURE (layer 26), CLAUDE.md.

CRITERIA (part 1)
  1 over stdio: diagnose the audience fault -> rooted tree; known fix ->
    verified; wrong fix -> not_resolved; in CI          PASS locally.
      Fault library, Docker, Windows: 13/13, mcp/auth-audience "verified,
      7 readings re-run twice", mcp/wrong-fix "not_resolved ... still
      failing on both runs: probe.auth.token_shape ...". In-process:
      TestTheLoopThroughMCP (both). In CI: the fault-library job runs
      TestTheFaultLibrary unfiltered (ci-cd.yml:405), so the mcp/ subtests
      run there — and it did: run 43045419342, both PASS on Linux.
      Note: the fix recreates order-service, and the MCP server running
      inside it with it, so diagnose and verify are two sessions; the
      state directory carries the investigation (LIMITS).
  2 an argument naming a grant, or a probe the environment does not
    grant, refused before anything is dialled (dials counted)  PASS.
      TestNoArgumentAcquiresACapability: five protocol refusals (grants,
      a capability as an argument name, capabilities on diagnose, grants
      on verify, grant on check), four tool refusals (an input named
      grants, an input named a capability, an ungranted probe, one
      ungranted probe beside a granted one) — 0 dials, 0 requests; the
      granted control then dials once. Shown red: with the pre-check
      disabled, "1 dial(s) and 0 request(s) for calls that were all
      refused". Also TestDiagnoseAndVerifyDialNothingUngranted (0 dials
      for a walk and a verification in an environment granting no network
      capability) and TestEditingCulpritYamlMidSessionGrantsNothing.
      The phase-auditor drove the real binary with 14 hostile lines and a
      counting TCP listener: nothing connected except a genuine call to a
      granted environment.
  3 every tool's response validates against the CLI's model   PASS, with
    the wording question below.
      TestEveryToolAnswersInTheCLIsModel: culprit_check equals `culprit
      check --format json` once parsed; readings, the Investigation and
      the Verification Validate() (decoded with unknown fields refused);
      culprit_system_model's intent is the CaptureBundle `culprit intent`
      prints (the auditor checked equality), every fact valid; the
      explanation's facts valid, its divergences check's own objects, each
      probe entry's capabilities and grant decision equal to the
      catalogue's and the environment's.
      NOT TESTABLE AS WRITTEN for two tools: culprit_system_model and
      culprit_explain_connection have no CLI command, so no CLI JSON. What
      holds: every record inside them is a model record that validates;
      their envelopes are new (Q22).
  4 links no network package beyond probe and capture; nothing calls a
    model                                                    PASS.
      check_test.go untouched; TestTheNetworkBoundaryIsAnAllowlist covers
      internal/mcp (go list ./internal/...), which links no net, net/http
      or crypto/tls; TestNothingInTheBinaryListens PASS;
      check_no_llm_imports covers cli/, cmd included. LLM_PROVIDER=none
      throughout the loop tests; nothing reads it.
  5 no tool writes                                           PASS.
      TestNoToolWrites: all six offered readOnlyHint, closed arguments;
      the whole loop leaves culprit.yaml's directory byte-identical; the
      protocol package links no Culprit package; mcp.go names no
      transport, os.WriteFile or os.Create. The only writes are the
      server's own state directory, as for the commands (LIMITS).

DELIBERATELY NOT BUILT (part 1's list and field 17)
  No narrator, no prose, no write-capable tool, no remediation, no network
  transport (stdio only; no listener), no change to the Python MCP server
  (mcp_server/ not in the diff). No LLM_PROVIDER=none CI job: it returns
  with the narrator in part 2 (D8, amended 2026-11-05).

GATES (local, Windows, Docker up)
  lint, typecheck, lint-imports, check-schema-drift, check-invariants,
  check-scan-coverage, check-frontend-tokens, check-security-doc,
  cli-lint, check-no-llm-imports, check_coupled_files --base origin/main
                                                                 PASS
  just test: api+scripts+shared 1297 passed / 6 skipped, worker 65,
    mcp_server 21, extractors 31 + node; go test ./... all ok      PASS
  culprit check --fail-on=breaks_request_path; LLM_PROVIDER=none  exit 0/0
  just fault-library (Docker): 13/13, results.json reproduced     PASS
    — run before the audit fixes; the fixes (pinning, input handling,
    the kind match) are covered by the in-process tests, and CI runs the
    library again.
  Not run locally: migration round trip (no migration), e2e (no api or
  frontend change) — CI runs both.

AUDITS
  invariant-auditor: CLEAN, no violation. Risks taken up:
    - culprit.yaml was re-read on every call, so an agent that can edit
      the repository could grant itself a capability between calls. Now
      the server pins the file's digest at start and refuses every call
      once it changes (TestEditingCulpritYamlMidSessionGrantsNothing).
    - The probe tool's description said "refused before anything is
      sent" without saying that is per declared capability; reworded, and
      LIMITS says an item-by-item grant is decided when the probe runs.
    - "443" as a string stayed a string where --input port=443 is an int;
      now the same rule as parseInputs (TestProbeInputsAreWhatTheCLIWouldPass).
    - The explanation picked probes by text prefix; now by the template's
      kind, compared with model.KindConnection / KindAuth.
    Left as risks, in LIMITS: error text can name local paths (the same
    text the command prints to stderr); diagnose and verify write the
    state directory under readOnlyHint; probe inputs are not bound to
    declared endpoints. Recorded only: `culprit probe` now reports a
    malformed --input before a missing culprit.yaml (exit 2 either way).
    It judged the Serve -> Run rename honest: TestNothingInTheBinaryListens
    matches by name, the method reads streams it is handed, and changing
    the test instead would have weakened it.
  phase-auditor: every criterion PASS (3 with the caveat above); work
    order complete; nothing from field 17 built. Fixed: a granted probe
    can reach any address the vantage can (LIMITS entry, Q23); the input
    filter compared capability names case-sensitively (now lower-cased);
    no dial-counted test covered diagnose and verify (added); the
    explanation's probe check validated the catalogue, not the entry
    returned (now compares them).

DECISIONS TAKEN HERE (for review)
  - The vantage is the server's (--from), not an argument: where the
    binary runs is a fact of how it was started, and a verification from
    anywhere else is refused anyway.
  - culprit.yaml is pinned for the session (above). A restart is needed
    to pick up an edit.
  - culprit_probe requires the probes to be named (the command's default
    is the whole catalogue, most of it refused), and refuses the whole
    call when any named probe's declared capabilities are not granted —
    a refusal the agent can act on, with nothing sent.
  - culprit_probe refuses an input whose name is a capability or
    grant/grants/capability/capabilities/allow, in any case.
  - culprit_system_model: components, connections, environments (adapter
    and grant names, not allowlist items), the vantage, and the INTENT
    bundle the walk uses. culprit_explain_connection: the connection, its
    and its auth relationships' facts and check divergences, and the
    probes whose readings are about a connection or auth relationship,
    with, for a named environment, whether each is granted. Neither
    probes anything.
  - Request handling is sequential and notifications/cancelled is
    ignored (LIMITS).
  - No outputSchema is published: an error result carries {error}, which
    a schema for the success shape would not admit.
  - The listener test matched the new method's name; the method was
    renamed Serve -> Run, the test untouched.

IN THE PLAN, FOR CORRECTION
  - Criterion 3 cannot be met literally for the two tools with no CLI
    command (Q22).
  - Fields 4-6 name worker/app/narrate and rag/prompts.py; already marked
    stale by "How Phase 35 is run" — part 2's.

/CI
  commit   b43ecd34360ded7851ab014b7aceb04d59f626a4 (merge result: origin/main
           0effc53 is an ancestor; merging it changes nothing)
  run      43045419342  CI/CD, pull_request — FAILURE, three attempts
  jobs     lint, typecheck, cli, test, migration-round-trip, kind-capture,
           self-check, fault-library, build x5: success; publish and
           deploy skipped; e2e: FAILURE on every attempt, at "Install
           just", before any test:
             E: Failed to fetch https://security.ubuntu.com/ubuntu/pool/
             universe/r/rust-just/just_1.45.0-1_amd64v3.deb  Temporary
             failure resolving 'security.ubuntu.com'
           (and azure.archive.ubuntu.com, archive.ubuntu.com; 20 such
           lines on attempt 3). AMBIENT: the runner could not resolve
           Ubuntu's mirrors. e2e is the only job that installs from apt
           (ci-cd.yml:513), so the only one hit. No e2e test ran, so the
           browser and agent journeys are NOT RUN on this commit.
  fault    TestTheFaultLibrary PASS (132 s) on Linux, mcp/auth-audience and
           mcp/wrong-fix PASS — criterion 1 in CI.
  checks   gh pr checks 34: 19 pass, 2 skipping, 1 fail (e2e); CodeQL pass
  alerts   none open (pr=34, refs/pull/34/merge, refs/pull/34/head)
  Verdict: NOT GREEN. Nothing in this branch's code is implicated; the
  gate is not met until e2e runs (Q24).

LEFT OPEN
  - Q24 (blocking the merge, not the design): e2e cannot install `just`
    while the runners cannot resolve Ubuntu's mirrors.
  - Q22 (criterion 3's wording), Q23 (binding probe inputs to declared
    endpoints) — neither blocking.
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
