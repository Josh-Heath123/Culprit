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
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35, with 31.1, 31.2, 32.1 and 32.2 inserted); then `docs/PERFORMANCE_PLAN.md` (Phases 36–39) |
| Current phase | **35, close-out** — `not started`. Brief: `DIAGNOSTIC_PLAN.md`, end of Phase 35, "Close-out". It brings `ec05453` and part 2's run report to `main`, with the review's corrections. Then **36, part 1**. |
| Previous phase | **35, part 2 — The narrator: signed off 2026-11-11** by the architecture session; complete when the close-out's merge is green on `main`. Merged via PR #35 (`ac0a939`). Every check on the pull request (run 43090673530) and on `main`'s push run (43092754729) was green, read from GitHub. Step 0 is met (run 43067489387), so part 1 is complete. The run continued after the merge: `ec05453` and the report (`356012e`) are on the branch, not on `main`. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-35-close-out`, to be cut from `origin/phase-35-narrator` = `356012e`. Its next commit is the Phase 35 part 2 sign-off already in the working tree (six files; message `../phase-35-2-signoff.txt`). Open a draft pull request and mark it ready when the run report is committed. Do not stage `shared/uv.lock`. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q22, Q23 and Q24 were ruled 2026-11-11 (`DIAGNOSTIC_PLAN.md`, end of Phase 35): criterion 3 accepted as built and reworded; `culprit_probe`'s address inputs bound to declared endpoints, as part 2's first item; no workflow change for `e2e` — re-run it. | | |

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
| 35, part 2 | The narrator | **complete when the close-out merges** (PR #35 merged, `ac0a939`) | **Signed off 2026-11-11** (architecture session): every check on the pull request and on `main`'s push run green, read from GitHub; step 0 met. Parity's widening (`8a09d7e`) is honest; Phase 36 part 2 narrows it. Merged before the run finished, so the re-audit's fixes (`ec05453`) and the run report (`356012e`) land with the close-out. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| 35, close-out | Land the re-audit's fixes; the review's corrections | not started | **Brief (2026-11-11):** `DIAGNOSTIC_PLAN.md`, end of Phase 35, "Close-out": its work order, criteria and what not to build. Branch `phase-35-close-out` from `origin/phase-35-narrator` = `356012e`; its next commit is the part 2 sign-off. The first run to open its pull request as a draft. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 36, part 1 | Budgets and the measurement | not started | **Brief (2026-11-11):** `docs/PERFORMANCE_PLAN.md` Phase 36: "How Phase 36 is run", then "Part 1" at the end of the section. Step 0: `main`'s push run on the close-out's merge green, both `e2e` legs and `narration-parity` included. Branch `phase-36-budgets` from `origin/main` at that merge. Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 36, part 2 | The walk sees slow | not started | `docs/PERFORMANCE_PLAN.md` Phase 36, "How Phase 36 is run". The brief and criteria are written at part 1's review. |
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
Phase:        35, part 2 — the narrator
Branch:       phase-35-narrator, from origin/main = 60d2c92 (PR #34's merge);
              its first commit is the part 1 sign-off (8e13685). PR #35.
Run:          2026-11-11, /next.
Status:       IMPLEMENTED; every local gate green; both audits run, every finding
              fixed, the phase-auditor's re-audit CLOSED on all six items.
              CI green on 8a09d7e (run 43090673530) on every job and every
              PR check, e2e (none), e2e (stub) and narration-parity included.
              The report commit's own run, which also carries ec05453, is
              below.

STEP 0
  main's push run on 60d2c92: run 43067489387, every job success, e2e
  included; deploy skipped. Part 1's gate is met.

WHAT WAS BUILT (work order 1-7)
  1 Q23. culprit_probe binds url, base_url, host and port to the endpoints
    the environment declares (endpoints:, a component's endpoint:): any
    other address refuses the whole call before anything is dialled, with
    the input and the reason. A redirect is bound the same way: through
    culprit mcp the HTTP client follows one only to a declared endpoint
    (probe.NewRealHTTPClientWithin). A host is compared as written, case
    aside — a trailing dot or a space is refused, not normalised. culprit
    probe from a terminal is unchanged. LIMITS rewritten for the two
    surfaces.
  2 shared/culprit_model/narration.py, pure: evidence() — the numbered
    list, from the record alone; check() — nine rules, one function each
    (citations name items; no URL; no invisible character; subjects,
    probes, capabilities, reading ids, code forms and components must be
    the investigation's); segments() — the prose with each citation
    replaced by its item's text from the record. What a refusal names is
    one token or a fixed label, URL-replaced, redacted, at most 80 chars.
    shared/tests/narration_conformance.json: 4 faithful, 24 refused, each
    breaking one rule. Written before any provider existed.
  3 Migration a6c2e9d4f8b1: narrations, one row per attempt with its final
    status; CHECKs hold what each status carries, attempts 1-3 unique per
    investigation; triggers refuse UPDATE, DELETE, TRUNCATE to every role.
    New role narrator: SELECT on the five investigation tables and
    narrations, INSERT on narrations. api-reader SELECT on narrations
    (same job, beside investigations; justified in the migration, revoked
    in the downgrade).
  4 worker/app/narrate: providers none (default), anthropic, ollama behind
    one interface, plain httpx; one call per attempt, a fixed system
    prompt and the evidence, no tools, no stream. Each attempt is claimed
    with an advisory lock before the call, so overlapping ticks cannot
    call twice; the claim is released even after a database error. Failures
    are Culprit's own words, redacted; a provider's
    error text is never read. Three attempts, retried no sooner than
    NARRATOR_RETRY_SECONDS (60). The narrator's tables live in app.narrate.
  5 GET /investigations/{id}/narration (api-reader): off, not_narrated,
    complete, failed, refused — never pending; the check runs again before
    prose is served. culprit_model.investigations.from_rows rebuilds an
    investigation for the API and the narrator alike, so evidence numbers
    agree. The page: a Narration card, badged Derived, beside the
    verifications; prose as text nodes; provider and model named.
  6 CI: e2e is a matrix, narration none and stub (scripts/narrator_stub.py,
    Ollama's /api/chat, scripted by a marker in the symptom). Both legs get
    the stub's model and address; only LLM_PROVIDER differs. The none leg
    asserts the stub had no call after every journey and the agent loop.
    narration-parity compares the agent loop's records across the legs.
    LLM_PROVIDER=none on the cli, self-check and fault-library jobs.
  7 README (feature row, "Narration, if you want it", providers incl.
    Ollama, D8), PERMISSIONS (the role; exactly what is sent; anthropic
    leaves the machine), SECURITY §7 (each "cannot" names its test),
    LIMITS (Narration, probe binding), ARCHITECTURE 27, UPGRADING, the
    database and determinism rules.

CRITERIA (part 2)
  1 culprit_probe refuses an undeclared address before dialling (dials
    counted): 169.254.169.254, an undeclared host, an undeclared port on a
    declared host; a declared endpoint dials once; red with the binding
    disabled; culprit probe unchanged                       PASS.
      TestAProbeReachesOnlyDeclaredEndpoints: 15 refusals, 0 dials, 0
      requests; the declared endpoint dials once and requests once. Red
      with the binding disabled: "5 dial(s) and 5 request(s) for calls that
      were all refused" (by hand, and again by the phase-auditor).
      TestARedirectIsBoundAsTheAddressIs (real loopback servers): red with
      the unbound client, "the undeclared server was reached 1 time(s)".
      TestCulpritProbeFromATerminalIsUnbound. TestEveryCatalogueInputIs-
      Classified fails on an input name nobody classified (shown red).
  2 the fixture refuses each case with what it named and passes faithful
    narrations; each rule red when disabled; a row inserted with unchecked
    prose is not served as prose                            PASS.
      test_narration.py: test_each_rule_is_load_bearing removes each of the
      nine rules and its cases get through; test_what_a_refusal_names_is_
      never_the_models_sentence_a_url_or_a_secret over every refusal and
      four hostile replies. test_narrations_api.py: an owner-inserted
      "complete" row naming an unknown subject, a bad citation and a URL is
      served as refused.
  3 with the stub, in CI: complete shown, derived, provider and model;
    failed with a reason, the stub's secret leaves no trace; refused with
    what it named; no fourth call; never pending              PASS in CI.
      e2e/narration.spec.ts (stub leg). Also locally: the worker's job
      tests against a real Postgres and the real ollama provider pointed at
      the stub (failure reason "ollama answered HTTP 500", no secret in the
      row or the log); test_three_attempts_then_no_fourth_call;
      test_overlapping_ticks_call_the_provider_once (red without the claim:
      4 calls).
  4 the narrator's input is built from the record alone (asserted); one
    call per attempt, no tools                                PASS.
      test_a_faithful_reply_is_stored_complete_after_one_call_built_from_
      the_record: calls == [(SYSTEM, render(evidence(record)))];
      test_the_evidence_is_the_record_and_nothing_else. anthropic: the
      request through httpx.MockTransport has exactly model, max_tokens,
      system, one message — no tools, no stream. The stub refuses a
      request offering tools.
  5 LLM_PROVIDER=none in CI: fault library, check/diagnose/verify, every
    e2e journey, no provider called (counted), the page says off; records
    identical on and off apart from ids and times             PASS in CI, with the wording
    question below.
      e2e (none): every journey, the agent loop (diagnose, a wrong fix, the
      right fix, verify) and the stub's /calls total == 0 with the stub's
      address given to the worker. narration-parity: the loop's
      investigation and verifications compared across the legs.
      NOT TESTABLE AS WRITTEN for the binary jobs (fault library, culprit
      check/diagnose/verify in the cli and self-check jobs): the binary
      reads no provider setting and links no model client, so there is
      nothing to count; held by construction (check_no_llm_imports over
      cli/, TestTheNetworkBoundaryIsAnAllowlist). The jobs set
      LLM_PROVIDER=none and pass.
  6 nothing downstream reads a narration; only app.narrate talks to a
    provider; no deterministic package imports it; lint-imports, shown red
    by a deliberate import                                    PASS.
      "only the narrator talks to a provider" and "nothing downstream reads
      a narration": both BROKEN with `import httpx` in app.anomaly.scorer
      and `from app.narrate import tables` in app.memory.link_job, KEPT
      without. test_narrate_boundary.py holds their source lists to every
      package in app/. check_no_llm_imports forbids app.narrate everywhere
      deterministic and now covers api/app.
  7 the narrator cannot update or delete a narration (a test tries); the
    migration round-trips                                     PASS.
      test_the_narrator_can_append_and_nothing_else (update, delete,
      truncate as narrator and as owner; no investigation write; no read of
      verifications or readings). check_migration_round_trip clean with two
      narrations seeded.
  8 markdown and HTML shown literally (e2e), refused if they carry a URL
                                                              PASS in CI.
      e2e: the markup reply's **, <b>, <script> appear as characters, no
      b/strong/script/img/a element; the refuse reply's markdown image is
      refused for its URL, no img rendered.

DELIBERATELY NOT BUILT (part 2's list)
  No hypothesis ranking. Nothing model-related in the binary (cli/ diff:
  mcp.go, mcp_test.go, probe/http.go, model/redact.go — no model). No tool
  for the narrator, no second call. No narration of verifications. No
  narration through culprit mcp. No streaming. No remediation applied. No
  button to narrate again.

GATES (local, Windows, Docker up), on ec05453
  lint, typecheck, lint-imports (6 kept), check-schema-drift (22 tables),
  check-no-llm-imports (9 packages), check-invariants, check-scan-coverage
  (303 files), check-frontend-tokens, cli-lint, check_security_doc (75
  references), check_coupled_files --base origin/main            PASS
  just test: api+scripts+shared 1400 passed / 6 skipped, worker 88,
    mcp_server 21, extractors 31; go test ./... all ok; frontend npm test
    19, oxlint, tsc                                              PASS
  check_migration_round_trip (Docker)                            PASS
  culprit check --fail-on=breaks_request_path, LLM_PROVIDER=none  exit 0
  NOT RUN locally: just quickstart, just e2e, just fault-library — the
  quickstart's infra/.env.prod is not readable in this session; CI runs
  all three.

AUDITS
  invariant-auditor: CLEAN, no violation. Risks taken up: a redirect
    carried culprit_probe past the binding (fixed, test above); a trailing
    dot compared as the declared host (now refused); the four bound input
    names unasserted (TestEveryCatalogueInputIsClassified); a scheme-less
    host/path not a URL (now is); the api handed ANTHROPIC_API_KEY by
    env_file (set empty for the api in both Compose files). Left: app.main
    is exempt from both contracts (it schedules the job); the contracts'
    forbidden list names third-party clients, not stdlib urllib or
    http.client.
  phase-auditor: NOT COMPLETE at 8bda31b, on four findings, all fixed in
    b50eff2: (1) a backticked span was stored and shown whole in what a
    refusal named — the model's sentence could reach the page; (2) the
    check missed capitalised subject kinds and reading ids, mailto:, and a
    zero-width character splitting a verdict; (3) overlapping ticks could
    call the provider four times for one attempt (reproduced); (4) the
    none leg had no stub address, so its zero count proved nothing. Also
    taken up: no test of the anthropic provider's request (added), and
    redact_credentials missed sk-ant-... keys (Python and Go, with a test
    each). Re-audited at 8a09d7e: all six items CLOSED (its own overlap
    test: 1 call; its redirect mutation red). Leftovers fixed in ec05453:
    combining marks and blank fillers splitting a verdict (now refused);
    host?query, host\path and host:port (now URLs); the claim's cleanup
    after a database error (the unlock failed and masked the error, the
    lock outlived it on a pooled connection — now rolled back first,
    test_a_database_error_mid_attempt_releases_the_claim, red before).
    Left, in LIMITS or here: a bare domain and a non-ASCII full stop are
    not URLs (text-only display); a named token can be 80 characters of
    the model's text joined by underscores; a tick that read due() before
    another wrote attempt N can make N+1 at once, skipping the retry
    interval (still at most three); an insert failing other than on
    uq_narrations_attempt writes no row and the next tick calls again —
    no CHECK the code can violate was found; plugin probes' inputs are
    not bound under culprit mcp (LIMITS).

DECISIONS TAKEN HERE (for review)
  - Providers over plain httpx, not the anthropic SDK: field 11 says no
    new dependency, httpx is already in the worker's lock (now declared),
    and the CI stub then runs the same request code.
  - The anthropic default model is unset: NARRATOR_MODEL is required with
    a provider, so which model reads an investigation is the operator's.
    anthropic-version 2023-06-01, max_tokens 16000.
  - Evidence carries no reading's measured values or evidence, only probe,
    target, verdict and reason (PERMISSIONS lists it).
  - The rebuild from rows moved into culprit_model.investigations.from_rows
    (the API's load used it alone before): numbering must agree.
  - narrations stores no refused prose — only what it named.
  - A stored narration is shown even after narration is turned off; "off"
    only when there is none.
  - The stub lives in scripts/ (scan coverage refused infra/), and its
    refusal names a component and a URL rather than a hand-formatted
    subject (the subject-construction lint).
  - e2e check names are now "e2e (none)" and "e2e (stub)"; main requires
    no checks by name (ruleset 26460341: deletion, non-fast-forward,
    update only).
  - Turning narration on narrates the stored history, newest first, three
    every 15 seconds (LIMITS).

IN THE PLAN, FOR CORRECTION
  - Criterion 5's "(counted)" cannot apply to the binary jobs: there is
    nothing to count. Suggested: "by construction — the binary reads no
    provider setting and links no model client".
  - Fields 4-6 (worker/app/narrate as a rewrite of rag) remain stale, as
    "How Phase 35 is run" says.

/CI
  run      43087534723 on 8bda31b — every job success except
           narration-parity: the legs' records differed by the run's agent
           named in a reason and a token's expires_in_seconds (3597 vs
           3598) — ids and times. Fixed in 8a09d7e.
  run      43090468335 on b50eff2 — the same narration-parity difference.
  run      43090673530 on 8a09d7e (pull_request) — SUCCESS
  jobs     lint, typecheck, cli, test, migration-round-trip, self-check,
           kind-capture, fault-library, e2e (none), e2e (stub),
           narration-parity, build x5: success; publish, deploy skipped
  e2e      (none): 19 passed, the four stub journeys skipped by design,
           "the stub provider's calls: {"total": 0}"; (stub): 22 passed,
           all four narration journeys; parity: "identical apart from ids
           and times"
  checks   gh pr checks 35: every check pass or skipping, CodeQL and the
           four Analyze checks included
  alerts   none open (pr=35, refs/pull/35/merge, refs/pull/35/head)
  merge    origin/main = 60d2c92, the branch's base: the branch is the
           merge result
  ec05453  pushed, but GitHub never synced PR #35 to it (no run in ten
           minutes; the PR head stayed 8a09d7e). The report commit's push
           carries it. That run is the one for the commit that writes this
           report, so it is recorded on PR #35, not here.

LEFT OPEN
  - The plan's criterion 5 wording (above, for correction).
  - The re-audit's leftovers listed under AUDITS, for review.
  - Definition of done: the recorded demonstration is Malcolm's, after
    the merge (not /next's).
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
