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
| Current phase | **35, close-out** — `awaiting decision` on Q25. Built and green: PR #36, CI run 43162985716 on `d89f37c`, every pull-request check pass or skipping. Work item 4 (`culprit mcp --plugins`) was not built: no plugin probe exists to gate (§3). Then **36, part 1**. |
| Previous phase | **35, part 2 — The narrator: signed off 2026-11-11** by the architecture session; complete when the close-out's merge is green on `main`. Merged via PR #35 (`ac0a939`). Every check on the pull request (run 43090673530) and on `main`'s push run (43092754729) was green, read from GitHub. Step 0 is met (run 43067489387), so part 1 is complete. The run continued after the merge: `ec05453` and the report (`356012e`) are on the branch, not on `main`. Decisions at the end of Phase 35 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-35-close-out` (PR #36, ready for review), from `356012e`; `origin/main` merged in. Do not stage `shared/uv.lock`. |
| Blocking questions | **Q25** — blocks the close-out's sign-off on work item 4 and criterion 6 only. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| 25 | **Close-out work item 4 and criterion 6 have no subject.** "`culprit mcp` serves the catalogue alone unless started with `--plugins`" and "with a plugin installed, `culprit mcp` without `--plugins` lists and runs no plugin probe" assume a plugin probe can be installed. None can: `catalogue()` is `probe.BuiltIn()` (`cli/cmd/culprit/diagnose.go:232`), and nothing else calls `Catalogue.Register`. `--no-plugins` governs extractor plugins (INTENT). Part 2's LIMITS sentence that led here was wrong and is corrected. Options: drop the item; or replace it with a test that `Catalogue.Register` is called only from `BuiltIn` (the phase-auditor's suggestion); or rule that `--plugins` should gate extractor plugins under `culprit mcp` (a different decision). Nothing was built for it. | 2026-11-12, close-out run | The close-out's sign-off (item 4, criterion 6) |

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
| 35, close-out | Land the re-audit's fixes; the review's corrections | **awaiting decision** (Q25); PR #36, CI green on `d89f37c` (run 43162985716) | **Brief (2026-11-11):** `DIAGNOSTIC_PLAN.md`, end of Phase 35, "Close-out". Criteria 1–5 PASS by execution, 6 NOT TESTABLE AS WRITTEN (Q25), 7 green on the pull request; `main`'s push run is Phase 36 part 1's step 0. Report in §5. |
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
Phase:        35, close-out — land the re-audit's fixes; the review's corrections
Branch:       phase-35-close-out, from origin/phase-35-narrator = 356012e;
              b7e4d03 the part 2 sign-off, 0836e41 the work, 4f5ba7a the merge
              of origin/main, d89f37c the audits' findings. PR #36 (draft
              until this report).
Run:          2026-11-12, /next.
Status:       AWAITING DECISION on Q25 (work item 4 and criterion 6 rest on
              a plugin probe that does not exist). Everything else built;
              every local gate green; both audits run, every finding taken
              up; CI green on d89f37c (run 43162985716), every PR check.

WHAT WAS BUILT (work order 1-5)
  1 characters_are_plain replaces no_invisible_characters:
    PLAIN_CHARACTERS holds U+0020-U+007E, newline, tab, the brief's
    typographic set and U+00A0; anything else is "a character outside
    plain text". Fixture: U+FF3F, U+02CD, U+2017 for the underscore, a
    Cyrillic letter in inventory-service (the three old invisible cases
    renamed to this rule); a faithful case with curly quotes, an em dash
    and an arrow. The prompt states the rule in words.
  2 The job: a row the database refuses is stored as failed, "the
    narration could not be stored" (logged by constraint name or error
    class only); count, done and the retry interval are read again under
    the claim (_attempts). If the failed row cannot be stored either,
    NarrationNotStored names the constraint and chains nothing.
    MAX_TOKENS = MAX_PROSE for anthropic's max_tokens and ollama's
    options.num_predict; an ollama reply with done_reason "length" fails,
    as anthropic's max_tokens stop already did (a cut reply would
    otherwise be stored complete, truncated — counted as part of the
    token bound, not a provider change).
  3 shown() in culprit_model.narration: a fixed label (LABELS) or one
    plain token with no whitespace, no URL, no credential, at most 80.
    The check names through it; the API serves every refused row, stored
    or re-checked, through it.
  4 NOT BUILT — Q25. culprit mcp's catalogue is probe.BuiltIn() alone
    (diagnose.go:232); nothing registers any other probe, so there is no
    plugin probe to gate. --no-plugins governs extractor plugins. The
    LIMITS sentence the decision rested on was wrong and is corrected.
  5 README and PERMISSIONS: turning narration on narrates the stored
    history, and with anthropic every stored investigation's evidence
    leaves the machine. LIMITS: the character rule and its cost (English
    only; a record's non-ASCII text can be cited, not copied), counted
    calls, the token bound, credential coverage, the probe binding.

CRITERIA (close-out)
  1 new fixture cases refused by characters_are_plain, through without
    it; the faithful case passes; red state recorded           PASS.
      test_each_rule_is_load_bearing[characters_are_plain]. Red, by hand
      and by the phase-auditor against ec05453's rule: U+FF3F, U+02CD,
      U+2017 and the Cyrillic case all pass it (passed=True).
  2 insert failing on a CHECK: one call, one failed row, no call next
    tick inside the interval; red without the change          PASS.
      test_an_attempt_whose_row_is_refused_is_stored_failed_and_counted.
      Red on b7e4d03's job.py: "assert 2 == 1" (two calls) — by hand and
      by the phase-auditor.
  3 two ticks that both read due() before either claims make one
    attempt                                                     PASS.
      test_ticks_that_read_due_before_either_claims_make_one_attempt;
      red on the old job, "assert 2 == 1".
  4 anthropic asks for at most MAX_PROSE tokens; ollama num_predict
    likewise                                                    PASS.
      test_anthropic_sends_one_message_no_tools_and_no_stream;
      test_ollama_asks_for_no_more_tokens_than_a_narration_may_hold.
  5 owner-inserted refused row naming a URL, a sentence and a credential
    served as labels and single tokens, none appearing         PASS.
      test_a_refused_row_is_served_as_labels_and_single_tokens_whatever_
      it_holds: ["a URL", "a name that cannot be shown", "a credential",
      "billing-service", 79 x + "…"]. Only credentials the shared pattern
      knows are caught (LIMITS).
  6 with a plugin installed, culprit mcp without --plugins lists and
    runs no plugin probe                     NOT TESTABLE AS WRITTEN — Q25.
      No plugin probe can be installed; confirmed independently by the
      phase-auditor (only BuiltIn calls Catalogue.Register).
  7 every PR check green, e2e (none), e2e (stub), narration-parity
    included                                                    PASS.
    main's push run on the merge                    NOT RUN — Phase 36
      part 1's step 0, after the merge.

DELIBERATELY NOT BUILT (the close-out's list)
  No change to the evidence, the record, the role or the providers beyond
  the token bound (and the cut-off reply it implies). No new narration
  feature. Nothing for Phase 36. No --plugins flag (Q25).

GATES (local, Windows, Docker up), on d89f37c
  lint, typecheck, lint-imports (6 kept), check-schema-drift,
  check-no-llm-imports, check-invariants, check-scan-coverage,
  check-frontend-tokens, cli-lint, check_security_doc (75),
  check_coupled_files --base origin/main                         PASS
  just test: api+scripts+shared 1414 passed / 6 skipped, worker 93,
    mcp_server 21, extractors 31; go test ./... 0 FAIL            PASS
  culprit check --fail-on=breaks_request_path, LLM_PROVIDER=none  exit 0
  NOT RUN locally: check_migration_round_trip (no migration changed;
  CI ran it), quickstart, e2e, fault library (CI ran all three).

AUDITS
  invariant-auditor: CLEAN. Risks: (1) a failed fallback insert chained
    the first error, whose text renders the failing row — fixed
    (NarrationNotStored, from None; test); (2) rows stored before the
    close-out are served differently: an old "an invisible character"
    becomes "a name that cannot be shown", and complete prose with a
    character outside the allowlist is now served refused — the safe
    failure, no data change; (3) the token comment overclaimed — fixed.
  phase-auditor: criteria 1-5 PASS by execution, 6 NOT TESTABLE AS
    WRITTEN, 7 not yet run at the time. Findings: F1 an en/em dash in a
    name passed the component rule — fixed (a joining dash is read as a
    hyphen; two fixture cases); F2 shown()'s "no credential" is the
    shared pattern's coverage (password=..., Slack tokens, user:pass@host
    pass) — in LIMITS, widening the pattern is a separate decision; F3
    overclaims about tokens — fixed; F4 the double-failure path — fixed;
    F5 the retry interval compares the worker's clock with Postgres's
    now() — harmless on one host, left. CLAUDE.md's phase line — fixed.

DECISIONS TAKEN HERE (for review)
  - An ollama reply cut off at num_predict fails, as anthropic's does.
  - shown()'s labels: "a credential", "a name that cannot be shown".
  - A joining en or em dash is a hyphen to the name rules (F1).
  - The branch's upstream was unset after cutting it from
    origin/phase-35-narrator, so no push could reach the merged branch.

IN THE PLAN, FOR CORRECTION
  - Work item 4 and criterion 6 (Q25).
  - "English runs well under one token per character ... no reply short
    enough to pass is cut off": a token is several characters, so 4000
    tokens bounds cost at a few times MAX_PROSE, not at it.

/CI
  run      43161287549 on 4f5ba7a (pull_request) — SUCCESS, every job
  run      43162985716 on d89f37c (pull_request) — SUCCESS
  jobs     lint, typecheck, cli, test, migration-round-trip, self-check,
           kind-capture, fault-library, e2e (none), e2e (stub),
           narration-parity, build x5: success; publish, deploy skipped
  checks   gh pr checks 36: every check pass or skipping, CodeQL and the
           four Analyze checks included
  alerts   none open (pr=36, refs/pull/36/merge, refs/pull/36/head)
  merge    origin/main = ac0a939 is merged into the branch (4f5ba7a): the
           branch is the merge result

LEFT OPEN
  - Q25 (blocks the close-out's sign-off on item 4 / criterion 6).
  - F2 and F5, above.
  - main's push run on the merge: Phase 36 part 1's step 0.
  - The definition of done's recorded demonstration is Malcolm's.
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
