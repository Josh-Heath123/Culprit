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
| Current phase | **36, part 1 — Budgets and the measurement** — implemented, awaiting review. PR #37; CI green on `3be789e` (run 43181751008), every pull-request check pass or skipping, no alert open. Report in §5. Then **36, part 2**, whose brief is written at this review. |
| Previous phase | **35, close-out — complete**, signed off 2026-11-12. PR #36 merged as `08f7d65`; `main`'s push run 43167772415 green on every job (part 1's step 0, recorded). **Phase 35 is complete, and with it `DIAGNOSTIC_PLAN.md`.** |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-36-budgets` (PR #37, ready for review), from `origin/main` = `08f7d65`. Do not stage `shared/uv.lock`. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q25 was ruled 2026-11-12 (`DIAGNOSTIC_PLAN.md`, end of Phase 35): close-out item 4 and criterion 6 are withdrawn, and a test that only `probe.BuiltIn` registers a probe joins Phase 36 part 1. | | |

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
| 36, part 1 | Budgets and the measurement | **implemented, awaiting review** (PR #37; CI green on `3be789e`, run 43181751008) | **Brief (2026-11-11, added to 2026-11-12):** `docs/PERFORMANCE_PLAN.md` Phase 36: "How Phase 36 is run", "Part 1" and "Added 2026-11-12". Every criterion PASS; 3 and 4 were NOT MET at the first audit and are fixed, with tests counted at the server. Report in §5. |
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
Phase:        36, part 1 — budgets and the measurement
Branch:       phase-36-budgets, from origin/main = 08f7d65 (PR #36's merge);
              10a09dd the close-out sign-off, fbdae75 the work, fb64c71 the
              audits' findings, 3be789e the re-audit's. PR #37 (draft until
              this report).
Run:          2026-11-12, /next.
Status:       IMPLEMENTED; every local gate green; both audits run, every
              finding fixed or written into LIMITS; CI green on 3be789e
              (run 43181751008), every PR check. Awaiting review.

STEP 0
  main's push run 43167772415 on 08f7d65 (PR #36's merge): every job
  success, e2e (none), e2e (stub) and narration-parity included; deploy
  skipped. Recorded, as "Added 2026-11-12" says; nothing re-run.

WHAT WAS BUILT (work order 1-6, and the Q25 item)
  1 The rule, first: shared/culprit_model/latency.py and
    cli/internal/model/latency.go, held to shared/tests/latency_conformance.json
    (16 judged cases with verdict and reason, 13 refused inputs). Integer
    only: nearest-rank order statistics, bounds at the exact binomial's
    ranks for 90% on each side (100^n and binomial coefficients; math/big
    in Go). fail when the lower bound is over, pass when the upper is
    within, inconclusive otherwise. A timeout sorts after every answer.
    Bounds: budget 1-60000 ms, samples at most 1e9 us, requests at most 50,
    in both languages.
  2 Budgets: budgets: in culprit.yaml (Go loader extract/budgets.go, rank
    100; culprit_model.latency.Budget; the API's manifest model, carried
    and round-tripped); x-culprit-budget on an OpenAPI operation (rank 80;
    a bad entry is a skip under want "budgets", not http_routes). Only
    latency_p50_ms and latency_p95_ms. One budget per subject and predicate
    in a file. Conflicts go through the unchanged comparator.
    diverge.Budgets lists budgets that point at nothing and, when budgets:
    is declared, the unbudgeted surface (routes declared `exists`);
    rendered in text and JSON. Budgets do not count as a second source
    for the unverifiable surface.
  3 probe.http.latency (cli/internal/probe/latency_probes.go, timing.go):
    50 GETs for a p95, 20 for a p50, sequential, >= 50 ms apart (also
    between runs in one process), each on a new connection, dialling to
    last byte (or the 1 MiB read cap), setup recorded as connect_us; no
    redirect, header, body or credential. The budget comes from
    expectation resolution, which now tries each predicate a manifest
    produces (only this probe has two; p95 first). The budget's subject
    fixes method and path: a non-GET budget, or a url on another path,
    sends nothing. Request timeout 2x budget + 500 ms, cut to what the
    120 s run has left. url and base_url are bound under culprit mcp.
    Probe ids named twice run once. cost: metered.
  4 Reading validation in Go (Reading.Validate) and Python (Reading), so
    POST /readings refuses a latency reading whose verdict its samples and
    budget do not give.
  5 The demo: an invariant declaring inventory-service's GET /ready, and
    its budget: latency_p95_ms 300. Chosen as well clear of both sides: a
    healthy /ready on the Docker network answers in milliseconds, and the
    library injects 800 ms; 300 sits ~2.7x under the fault and far above
    healthy, and at p95 a pass needs all 50 samples within it, so a margin
    that wide keeps the healthy case from being held inconclusive by one
    slow request. The fault library runs culprit probe probe.http.latency
    under the latency fault and after its fix.
  6 PROBES (catalogue row and a section), PERMISSIONS (net.http.outbound:
    what the probe sends, no new capability), LIMITS ("Latency budgets"),
    README ("Latency budgets", budgets: and x-culprit-budget), ARCHITECTURE
    28, CLAUDE.md. The tour waits for part 2.
  Q25 register_test.go type-checks every non-test package of the module
    (module packages from source, others stubbed: 0.1 s) and fails on any
    call or method value of a Register that is Catalogue's or takes a
    probe.Probe, outside probe.BuiltIn — in function bodies, package-level
    initializers and testdata directories. TestCulpritMcpServesTheBuiltIn-
    Catalogue holds what the binary serves to BuiltIn's 14.

CRITERIA (part 1)
  1 the rule's fixture holds in Go and Python, same verdicts and reasons,
    with the six named cases; red by moving a bound one rank   PASS.
      TestTheLatencyRuleGivesTheFixturesVerdictAndReason, test_the_rule_
      gives_the_fixtures_verdict_and_reason; ranks checked by hand in
      both (p50 of 20: 7 and 14; p95: 44 none, 45 yes). Moving either
      bound one rank turns cases red in both. The phase-auditor recomputed
      ranks with exact fractions for n=1..50 (0 mismatches) and fuzzed Go
      against Python on 40,000 inputs including bounds: 0 differences.
  2 against a fake server, counted: under passes, over fails, straddling
    inconclusive, mostly 401/500 inconclusive, a timeout counts as slow
                                                              PASS.
      TestTheLatencyProbeAgainstAServerWithControlledDelays (httptest).
  3 nothing makes it send more than 50 or closer than 50 ms; a test tries
    each                                                      PASS.
      TestNothingMakesTheLatencyProbe... (inputs, a probes: timeout
      override, the strictest budget, credentials as inputs);
      TestTwoLatencyRunsAtOnceDoNotInterleave; TestALatencyProbeNamedTwice-
      RunsOnce and ...ListedTwiceOverMCPRunsOnce (red without the
      de-duplication: 40 requests). NOT MET at fbdae75 (phase-auditor:
      `-p x -p x` sent 100 requests 0.1 ms apart); fixed in fb64c71, its
      reproduction then 50 requests, 50.9 ms apart. Two separate processes
      at once can still interleave (LIMITS).
  4 a non-GET budget is inconclusive with nothing sent; never OPTIONS,
    HEAD, a body or a credential                              PASS.
      TestABudgetOnARouteThatIsNotGetSendsNothing, TestAPostBudgetSends-
      NothingWhateverTheInputsSay, TestAUrlOnAnotherRouteSendsNothing (all
      counted at the server); neverSentAnythingButAPlainGET on every
      server test. NOT MET at fbdae75 (a url input made a POST budget
      timed GETs); fixed in fb64c71; the re-audit then found a url on
      another path judged against the budget; fixed in 3be789e.
  5 through culprit mcp, the address input refuses an undeclared endpoint
    before dialling (counted); classification covers it       PASS.
      TestAProbeReachesOnlyDeclaredEndpoints (3 latency cases, 0 requests);
      TestEveryCatalogueInputIsClassified. Red by the phase-auditor with
      the binding removed (overlay).
  6 culprit check: conflicting budgets -> intent_conflict; a budget on an
    undeclared route reported; unknown predicate refused by the Go loader,
    the Python model and the API's model                      PASS.
      check/budgets_test.go; test_latency.py (Budget);
      test_manifest_budgets.py.
  7 a latency reading whose verdict disagrees is refused by Go, Python and
    the API, each shown red                                    PASS.
      Validators disabled by hand: Python + API 18 failed; Go
      TestALatencyReadingWhoseVerdict... failed. Reproduced by the
      phase-auditor.
  8 in CI's fault-library job, on Linux: fails under the latency fault,
    passes once cleared                                        PASS in CI.
      measureLatency in faultlib_test.go; run 43175231182 and run 43181751008:
      TestTheFaultLibrary/latency PASS. expected.json and results.json
      unchanged.
  9 from a fresh clone, the quickstart starts with the demo's budgets:
                                                              PASS in CI.
      Both e2e legs apply demo-services/culprit.yaml from a fresh
      checkout; test_manifest_budgets.py loads and round-trips it.
  10 every PR check green, both e2e legs and narration-parity;
    LLM_PROVIDER=none changes nothing                          PASS.
  Q25 only probe.BuiltIn calls Catalogue.Register, shown red   PASS.
      TestOnlyBuiltInRegistersAProbe; TestARegistrationElsewhereIsFound
      (a direct call, a package-level initializer, a call through an
      interface, a package under testdata). Not caught by a source scan:
      registration by reflection; TestCulpritMcpServesTheBuiltInCatalogue
      holds the served catalogue instead.

DELIBERATELY NOT BUILT (part 1's list)
  No walk change (isolate, verify, the library's verdicts untouched; the
  probe discriminates nothing, so the walk never picks it). No credential.
  No OPTIONS or HEAD. No parallel requests, configurable count or load. No
  percentile but p50 and p95. No telemetry percentiles. No threshold
  Culprit chose: the demo's 300 ms is the demo's declaration, with its why.

GATES (local, Windows, Docker up), on 3be789e
  lint, typecheck, lint-imports (6 kept), check-schema-drift,
  check-no-llm-imports, check-invariants, check-scan-coverage, cli-lint,
  check_security_doc (75), check_coupled_files --base origin/main  PASS
  just test: api+scripts+shared 1506 passed / 6 skipped, worker 93,
    mcp_server 21, extractors 31; go test ./... 0 FAIL             PASS
  culprit check --fail-on=breaks_request_path, LLM_PROVIDER=none   exit 0
  NOT RUN locally: quickstart, e2e, fault library, migration round trip
  (no migration); CI ran all of them.

AUDITS
  invariant-auditor: CLEAN. Risks taken up: the rank functions were
    exported mutable vars any package could swap (now unexported seams);
    "last byte" overstated past the 1 MiB read cap (documented). Left:
    TimeGet builds its own request, outside do()'s method check (a
    constant GET); no limit across separate invocations; Resolve now tries
    every Produces entry (only this probe has two).
  phase-auditor: NOT COMPLETE at fbdae75 — criteria 3 and 4 NOT MET (A, B
    above), with C a whole-float budget accepted by Go and refused by the
    API, duplicate budgets silently dropped; D two evasions of the Q25
    test; E a huge budget overflowing the timeout into a fail with nothing
    sent; F large budgets sending almost nothing; G Python accepting
    values Go refused. All fixed in fb64c71. Re-audit at fb64c71: A, B,
    C, E, F, G CLOSED; two new — a url on another path (fixed in
    3be789e), and a package under testdata hidden from the scan (fixed).
    Left, in LIMITS or here: two processes at once can interleave;
    `1e3`/`0o454` read differently by the two YAML readers; registration
    by reflection is not caught by the source scan (the served catalogue
    is held instead). The fixes in 3be789e were not re-audited; they are
    tested and the tests counted at the server.

DECISIONS TAKEN HERE (for review)
  - A budget is 1-60000 ms (model.MaxBudgetMS, MAX_BUDGET_MS): a bound on
    what can be declared, so a timeout can mean "slower than the budget"
    inside the 120 s run, not a judging threshold. Samples at most 1e9 us.
  - Request timeout 2x budget + 500 ms, cut to the run's remaining time;
    the probe's run is 120 s.
  - When a route has both budgets, the p95 is measured.
  - The budget's subject fixes method and path; inputs that disagree send
    nothing.
  - Duplicate budgets in one file are refused at load.
  - A refusal, redirect or failed connection is "not a sample", counted as
    not_samples.
  - The demo's GET /ready is declared by an invariant (the walk follows
    only `calls`, so the walk is unchanged).
  - The fault library runs the probe from the latency fault's vantage
    (order-service) with --input base_url.

IN THE PLAN, FOR CORRECTION
  - Field 4 and 12 still name OPTIONS; superseded by "How Phase 36 is run".
  - Field 10's "10 to 50 requests" is superseded (fixed 20 / 50).
  - Criterion 3 as written misses separate processes; the cap is per run
    and per process.

/CI
  run      43175231182 on fbdae75 — SUCCESS, every job
  run      43179287944 on fb64c71 — SUCCESS, every job
  run      43181751008 on 3be789e (pull_request) — SUCCESS
  jobs     lint, typecheck, cli, test, migration-round-trip, self-check,
           kind-capture, fault-library, e2e (none), e2e (stub),
           narration-parity, build x5: success; publish, deploy skipped
  checks   gh pr checks 37: 22 pass, 2 skipping (publish, deploy), CodeQL and the
           four Analyze checks included
  alerts   none open (pr=37, refs/pull/37/merge, refs/pull/37/head)
  merge    origin/main = 08f7d65 is an ancestor of the branch: the branch
           is the merge result

LEFT OPEN
  - The audit leftovers above, for review.
  - Part 2's brief and criteria (written at this review).
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
