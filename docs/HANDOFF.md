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
| Current phase | **34, part 1 — The loop, in the binary** — status `in progress`: implemented, every criterion executed and passing locally (the fault library 11/11 under Docker), both audits run and their findings fixed; committed and pushed, pull request open, `/ci` recorded in §5. Q20 and Q21 for review, neither blocking. |
| Previous phase | **33 — The production agent and the permission model: complete** (three parts), part 3 signed off 2026-11-10 by the architecture session. Part 3 merged via PR #31 (`e125b4b`), every pull-request check green, no open alert. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`; Q19 ruled there. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-34-verify`, cut from `origin/main` = `e125b4b`; its first commit is the Phase 33 sign-off. Lands through a pull request. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** Q20 and Q21 are open and do not block (§3). |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q20 | **A fix that is none of image, config key or commit.** The decided change kinds are an image, a config key, or a commit. Three of the fault library's fixes are runtime actions — the partition's firewall rule removed, the injected error rate and latency cleared — so part 1 names them as `commit:<ref>` with a ref derived from the fix's name (`cli/testdata/faultlib/expected.json` says so), because no real commit applied them. A commit explains nothing a capture records, so the verdict still rests on the readings and on the environment not having changed: nothing is called verified that the readings do not show. But the record says "commit" for something that was not one. Should part 2 add a fourth kind (an operator's action, described, explaining nothing), or should the library apply those fixes as config changes instead? | 2026-11-10, Phase 34 part 1 | Nothing in part 1. Part 2's change vocabulary, and how the README describes the library's outcomes. |
| Q21 | **Criterion 3 and a fault the walk cannot see failing.** "For every fault class in the library: inject, diagnose, apply the known fix, verify — `verified`." The latency fault slows every request without failing any, so its diagnosis is partial with no failing reading, and no fix can be *seen* to fix it: its verification is `inconclusive`, with that reason, and the library asserts exactly that. Five classes reach `verified`; the audience fault under narrower grants is `inconclusive` because its probe is still refused. Proposed wording: "for every fault class the walk diagnoses with a failing reading: ... `verified`; a diagnosis with no failing reading: `inconclusive`, saying so." Accept, or should latency be made detectable (a latency budget the walk can fail against) first? | 2026-11-10, Phase 34 part 1 | Nothing in part 1. Whether part 1's criterion 3 is met as written. |

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
| 34, part 1 | The loop, in the binary | in progress — PR open, `/ci` in §5 | **Brief (2026-11-10):** `DIAGNOSTIC_PLAN.md` Phase 34 — all 17 fields, read with "How Phase 34 is run" at the end of the section, which wins where they differ; then "Part 1" there for the work order, the criteria and what not to build. The `Verification` model and its conformance fixture come first. No API, migration or interface. Branch `phase-34-verify`. Lands through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 34, part 2 | Outcomes in the control plane | not started | Criteria written at part 1's review. First item: Q19's column grant. |
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
Phase:        34, part 1 — the loop, in the binary
Branch:       phase-34-verify, from origin/main = e125b4b; its first commit is
              the Phase 33 sign-off (5c56ff5). Commits f35e37f..HEAD.
Run:          2026-11-10, /next.
Status:       IMPLEMENTED. Every criterion executed and passing locally, the
              fault library included (Docker, 11/11); both audits run and
              their findings fixed. /CI: below. Two questions for review
              (Q20, Q21), neither blocking.

WHAT WAS BUILT (work order 1-5)
  1 The Verification model (f35e37f), Go (cli/internal/model/verification.go)
    and Python (shared/culprit_model/verifications.py), with
    shared/tests/verification_conformance.json written first: 20 accepted
    cases (every verdict), 33 rejected, 10 "what a change touches". The
    verdict is a pure function of the record — model.Judge / judge(): the
    re-runs (two each), the changes named, the captures before and after,
    the differences. Both refuse a record whose verdict or clause flags the
    record does not support, so `verified` cannot be built with a clause
    false — in code, from a file, or (Go) by encoding one.
  2 `culprit diagnose` captures the environment under its own grants before
    the walk, and keeps the investigation, the request behind every reading
    (isolate.Walk.Requests; the counterfactual's under the reference
    environment) and the capture as a sealed envelope, in the state
    directory ($CULPRIT_STATE_DIR, else the user's state directory; 0600).
    With no capture allowed, the rubric's `verified` reason says why
    ("...because the capture of X recorded nothing (refused: ...)").
  3 cli/internal/verify and `culprit verify <id> --change ... --from ...`
    (b0bde12): checks the record covers every reading; refuses a vantage
    other than the diagnosis's; re-runs every request twice through a
    Runner (probes under the environment's current grants); captures again;
    compares before and after with diverge.CompareAll (the engine
    `culprit diff` uses, the two captures as two scopes); judges. Exit 0
    verified, 1 any other verdict, 2 could not run. Links no network
    package: the D8 allowlist is unchanged.
  4 The fault library (d3ab1af): every fault injected, diagnosed, fixed with
    its known fix and verified, in its vantage, with the change named; plus
    four scenarios — wrong fix, regression, change underneath, no change.
  5 LIMITS ("Verification", eleven entries), PROBES, PERMISSIONS, README,
    UPGRADING, ARCHITECTURE, CLAUDE.md.

CRITERIA (part 1)
  1  conformance fixture holds in Go and Python, incl. a verified
     with one clause false neither can construct          PASS. Go
       TestVerification* / TestAVerifiedVerificationCannotBeConstructed...;
       Python 369 shared tests. Six "verified with its first/second/third
       clause false" cases; the phase-auditor corrected only verdict and
       flags on each and each then validates — rejected for the clause.
  2  re-runs exactly the investigation's probes, count asserted,
     no stored reading reused                              PASS.
       TestEveryReadingIsMeasuredAgainTwiceAndNoneIsReused (runs ==
       2 x readings; fresh runner stamps); TestTheLoopEndToEnd (real
       command, real server: same ids and order, every run after closed_at);
       the fault library ("7 readings re-run twice").
  3  every fault class: inject, diagnose, fix, verify -> verified,
     in CI                                                  PASS for the
       five whose diagnosis has a failing reading: auth-audience,
       network-partition, contract, config, error-rate -> verified. NOT AS
       WRITTEN for latency: the walk finds no failing reading, so nothing
       can be seen fixed -> inconclusive, with that reason (Q21).
       auth-audience-ungranted (the audience class under narrower grants)
       -> inconclusive: "...was refused: ... config.inspect.values is not
       granted". In CI: /ci below.
  4  a wrong fix -> not_resolved                             PASS. Library
       verify/wrong-fix: a token re-minted for 'inventory-svc': "still
       failing on both runs: probe.auth.token_shape on the token audience
       order-service presents to inventory-service (r5, r7)".
  5  a fix that breaks a passing probe -> regressed           PASS.
       verify/regressed: contract fixed, payments-service erroring: "these
       passed before and fail now: probe.http.reachable on payments-service
       (r2)".
  6  a config key changed on another component ->
     changed_underneath                                     PASS.
       verify/changed-underneath: contract fixed (inventory-service), a key
       added to order-service: "...where the change to CONTRACT_FAULT in
       inventory-service's configuration does not explain it:
       CULPRIT_UNRELATED_FLAG in order-service's configuration (exists)".
       Also in-process (TestTheLoopEndToEnd). Caveat: under the process
       adapter only the vantage's own config is captured (LIMITS).
  7  a flip, no change named, no before -> inconclusive     PASS. Flip:
       TestTheVerdicts/a_result_that_flips and the fixture (unit level).
       No change: library verify/no-change-named and in-process. No
       before: in-process, environment `blind` — the investigation says
       why, the verification is inconclusive.
  8  D8 allowlist unchanged; LLM_PROVIDER=none changes nothing PASS.
       check_test.go untouched; TestTheNetworkBoundaryIsAnAllowlist PASS;
       `go list -deps ./internal/verify` has no net, net/http, crypto/tls.
       Nothing in cli/ reads LLM_PROVIDER; the loop test runs with it none.

  Real comparison seen working in the library: the config fix's
  verification found one difference (PAYMENTS_PROVIDER_KEY appearing) and
  explained it by the change named.

GATES (local, Windows, Docker up)
  lint, typecheck, lint-imports, check-schema-drift, check-no-llm-imports,
  check-invariants, check-scan-coverage, check-frontend-tokens,
  check-security-doc, cli-lint, check_coupled_files --base origin/main PASS
  go test ./... (16 packages)                                   PASS
  api+scripts+shared 1233 / 6 skipped, worker 65, mcp 21        PASS
  culprit check --fail-on=breaks_request_path / LLM_PROVIDER=none exit 0 / 0
  just fault-library (Docker): 11/11                             PASS
  Not run locally: e2e, migration round trip (no migration, no api or
  frontend change) — CI runs both.

AUDITS
  invariant-auditor: ONE VIOLATION, fixed. The Python model accepted a
    difference whose subject is not a subject URI, and blank ids, where Go
    refused them; and the two disagreed on an empty subject or ref. Now
    Python parses the subject and refuses blanks, both read "" as absent,
    and the fixture has a case for each (the drift would have been caught).
    Risks taken up: verify now takes --from and refuses another vantage;
    diagnose keeps files only after the investigation validates; a failure
    to keep no longer puts a local path into the investigation; PERMISSIONS
    says what a grant added since diagnosis does. Left as risks, in LIMITS:
    recorded inputs are re-used as written (same probe, target and
    environment, checked); Windows ACLs, not 0600, protect the state
    directory.
  phase-auditor: every executable criterion PASS locally; NOT YET COMPLETE
    on the handoff (this report), CI, and criterion 3 for latency (Q21).
    Fixed: the vantage (its finding 2, the same as the invariant risk);
    PROBES' wording on refusals (not_resolved and regressed take
    precedence). Noted for part 2: the agent's walk takes no before and
    says only "no change has been verified" (LIMITS); the type cannot
    check that runs post-date the investigation or that `was` matches it —
    the API must, once it stores verifications; a commit ref is checked
    for form, not existence (Q20).

DECISIONS TAKEN HERE (for review)
  - The verdict lives in the model: Judge is the rules, and both languages
    refuse any other verdict. verify computes nothing it could disagree on.
  - Re-runs carry their own environment: a counterfactual reading is re-run
    in its reference environment and judged with the rest; only the
    investigation's environment is captured before and after (LIMITS).
  - Field 7's `reran [reading_id]` is a list of re-runs (id, was, probe,
    target, environment, both readings), so a verification can be checked
    from itself; `changes_explained` is the third clause's flag beside
    failing_now_passes and no_regressions.
  - What a change explains: a config key, that key; an image, that
    component's image and packages (not config keys its ENV sets); a
    commit, nothing a capture records.
  - The record of each reading's request (inputs included) and the capture
    live in a local state directory, not in the investigation: adding a
    field to the investigation would be refused by POST /investigations'
    model, and part 1 has no API change.
  - A capture with no facts is no record of before: comparing two empty
    captures would call every change "nothing changed".
  - Field 10's `verify:` (reference environment, regression tolerance) not
    built: a regression tolerance contradicts "every reading that passed
    still passes", and the reference is the diagnosis's own.

LEFT OPEN
  - Q20 (change kinds for runtime fixes), Q21 (criterion 3 and latency).
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
