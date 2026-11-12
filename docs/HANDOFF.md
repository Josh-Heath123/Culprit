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
| Current phase | **37, part 1 close-out** — `not started`. Brief: `docs/PERFORMANCE_PLAN.md`, end of Phase 37, "Close-out of part 1". Step 0: `main`'s push run on `b3ef508` green; then the phase-auditor re-audits `25db425`. Then **37, part 2** (briefed). |
| Previous phase | **37, part 1 — Reading the database safely: signed off 2026-11-12** by the architecture session; complete when the close-out merges. PR #39 was merged as `b3ef508`; the pull request's runs 43263355094 and 43267638088 were green on every job, read from GitHub. Q27 is ruled: package isolation. **Phase 36 is complete**: `main`'s push run 43250669431 on `d785af4` was green. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-37-closeout`, to be cut from `origin/main` = `b3ef508`. Its first commit is the part 1 sign-off, already in the working tree (`docs/PERFORMANCE_PLAN.md`, `docs/HANDOFF.md`; message `../phase-37-1-signoff.txt`). Open a draft pull request and mark it ready when the run report is committed. Do not stage `shared/uv.lock`. |
| Blocking questions | None. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| — | None open. Q27 was ruled on 2026-11-12 (`PERFORMANCE_PLAN.md`, end of Phase 37): package isolation for the guarded HTTP client and the database session, each a package with one non-test file whose exported surface names no `net/http`, `net` or `pgx` type, and the network allowlist names both. It is built in the close-out. | | |

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
| 36, part 1 | Budgets and the measurement | **complete when `main`'s push run on `716205f` is green** (PR #37 merged) | **Signed off 2026-11-12** (architecture session): every check on the pull request green, read from GitHub. The phase-auditor recomputed every rank with exact fractions and fuzzed Go against Python on 40,000 inputs; its two NOT MET findings were fixed and counted at the server. Three corrections are carried into part 2. Decisions at the end of Phase 36 in `PERFORMANCE_PLAN.md`. |
| 36, part 2 | The walk sees slow | **complete** (PR #38 merged, `d785af4`; `main`'s push run 43250669431 green) | **Signed off 2026-11-12** (architecture session): every check on the pull request was green, read from GitHub. The library's latency fault roots at inventory-service and verifies; a wrong fix gives `not_resolved`; without budgets it is `inconclusive`. Q21 is closed. Q26 is ruled, and Q27 corrected its premise. Decisions are at the end of Phase 36 in `PERFORMANCE_PLAN.md`. |
| 37, part 1 | Reading the database safely | **complete when the close-out merges** (PR #39 merged, `b3ef508`) | **Signed off 2026-11-12** (architecture session): every check on the pull request was green, read from GitHub; a read-only session refused at the server in CI; the demo's database is seeded, and index facts are found both ways. Q27 is ruled: Q26's premise and "one file" were wrong, because Go's visibility is per package, so package isolation follows. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 1 close-out | Package isolation; one schema for both manifest readers | not started | **Brief (2026-11-12):** `docs/PERFORMANCE_PLAN.md` Phase 37, "Close-out of part 1": its work order, criteria and what not to build. Step 0: `main`'s push run on `b3ef508` green, then the phase-auditor re-audits `25db425`. Branch `phase-37-closeout` from `origin/main` = `b3ef508`; its first commit is the part 1 sign-off. Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 37, part 2 | Statements and plans | not started | **Brief (2026-11-12):** `docs/PERFORMANCE_PLAN.md` Phase 37, "Part 2" at the end of the section. It starts after the close-out merges; step 0 confirms `main`'s push run on that merge. Branch `phase-37-statements` from that merge. Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 37, part 3 | The database in the walk | not started | `docs/PERFORMANCE_PLAN.md` Phase 37, "How Phase 37 is run". The brief and criteria are written at part 2's review. |
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
Phase:        37, part 1 — reading the database safely
Branch:       phase-37-database, from origin/main = d785af4 (PR #38's merge);
              b20dfc5 the Phase 36 sign-off, 155c7eb the carried-in items,
              fcd0b0a the database work, then the audits' fixes and this
              report. PR #39.
Run:          2026-11-12, /next.
Status:       AWAITING DECISION (Q27, blocking). Built; every local gate
              green; CI green on fcd0b0a (run 43263355094, every job). The
              phase-auditor: PHASE NOT COMPLETE — criterion 1 NOT MET, and
              Q26's premise is false, for one reason: in Go, another file
              in the same package can use a value without importing its
              type. Fixing it means new packages that link the network,
              so the network allowlist test would have to name them: an
              escalation (§6), not mine to decide.

STEP 0
  main's push run 43250669431 on d785af4: every job success (fault library,
  e2e (none), e2e (stub), narration-parity); deploy skipped.
  The phase-auditor re-audited 4c7bc6e's manifest and fixture changes:
  OPEN — the API's reader counted merged budgets: sections as "written
  twice" (it refused three files the Go loader loads), and an anchored
  value (`&v 300`) was plain to Go only; LIMITS' "one split remains" was
  false. Fixed in 155c7eb: the API reads budgets: as yaml.v3 does (a key
  written twice in any mapping refused; the root's own budgets: before a
  merged one, the first merge before a later; only that section
  form-checked; a non-string top-level key refused); Go treats an anchor as
  not plain; budget_manifests holds both readers to every case with what
  loads (red on the old reader: 5 cases; Go: the anchor).

WHAT WAS BUILT (work order 1-7)
  1 Carried in (155c7eb):
    - redact_credentials, Go and Python, from shared/tests/
      redaction_conformance.json: password=… outside a URL, Slack tokens,
      user:pass@host, and (after the audit) SQL's PASSWORD '…'. Python now
      removes a whole private-key block, as Go did. Red without: Go 14
      mismatches, Python 9.
    - Q26: the 26-form method scan is retired. Only http.go and timing.go
      may import net/http (allowlist test, red with a third file, aliased,
      or a package under net/http); every client comes from
      newGuardedClient, which installs methodGuard (red for a literal, new,
      a value, the default client, an embedding, a replaced transport, a
      transport through a pointer, a direct or stored RoundTrip, an aliased
      import); the guard refuses a non-GET or a body as it leaves; a
      request changed after it was built (method, pointer to the method,
      body) is refused at a real server, counted 0.
    - planned required by the rule in Go and Python, so by the API;
      probe.http.latency version 2; a fixture case without it.
    - shared/tests/manifest_keys.json: both readers know the same top-level
      keys; the API's model gains probes: and isolation:, validated as Go
      validates them and exported whole.
  2 db.stats.read, db.plan.read: Go, Python, the shared fixture, the
    frontend's plain words; the agent's parser and the allowance take them
    by name. TestNoCapabilityImpliesAnother (every pair);
    TestAnAllowanceNarrowsTheDatabaseCapabilities. No probe declares them
    until part 2, so the probe catalogue is unchanged by them.
  3 The boundary (internal/capture/database.go): the only non-test pgx
    importer (allowlist test, red with a second); statements are an
    unexported type of constants, checked by a switch (after the audit:
    it was a map an init() could extend); send is the only driver call in
    the file and refuses anything else first (counted at a fake driver: an
    arbitrary statement, EXPLAIN ANALYZE, a reset, a second statement
    appended — 0 reached it); openSession sets read-only, a 10 s
    statement timeout and application_name as connection parameters.
    Capture and the database probes run through it unchanged.
  4 pg_stat_statements: the quickstart's Postgres starts with
    shared_preload_libraries=timescaledb,pg_stat_statements, set
    explicitly; the recipe reads the running value and stops if it is
    missing. CI e2e: "shared_preload_libraries: timescaledb,
    pg_stat_statements". The image's own default was NOT observed: the
    list is set rather than measured, and it replaces the default
    (Culprit's database needs only timescaledb; LIMITS and the compose
    comment say so).
  5 The demo's database (P8): inventory-service's own Alembic migrations
    (products: id primary key, sku unique index, category not indexed) and
    a seed migration of 1,000,000 rows in 200 categories, generated in the
    database. Why that size: a sequential scan of one category reads the
    whole ~80 MB table (tens to hundreds of ms), an index on category would
    read 5,000 rows (well under 1 ms) — a gap wider than any statement
    budget part 3 should declare, on a laptop or a runner. Set up by
    inventory_service/setup_db.py, run by `just quickstart` as a one-shot
    service: as the server's superuser it creates the inventory role and
    database and pg_stat_statements there (not a trusted extension, so the
    owner cannot — a deviation from "done by its migrations as their
    owner"), then applies the migrations as the inventory role. GET
    /products?category=…; 503 without a database (the fault stack).
    culprit.yaml declares inventory-db, its edge `background`: POST
    /orders never reads it, and on the request path it would change every
    walk the fault library checks. CI e2e: "inventory's products: 1000000
    rows".
  6 Index facts: leads_index on the column-level schema: subject, true or
    false for every column. CONFIGURED from capture (a fourth template:
    valid, non-partial, non-expression indexes' first column); INTENT from
    the migration reader (create_index, drop_index, constraints, column
    flags, renames, drops). The generic comparator compares them; absence
    is not judged for it, so a missing table adds no index finding.
  7 PERMISSIONS (db.metadata.read's four statements, the two capabilities,
    the recommended role and that it can read rows), LIMITS (indexes, the
    boundary and what it does not hold, the GET-only rule, the readers'
    splits, redaction, the quickstart's database), README (Databases),
    CLAUDE.md.

CRITERIA (part 1)
  1 nothing outside the template set reaches the database; an arbitrary
    statement and EXPLAIN ANALYZE refused before they leave, counted; the
    allowlist fails on a second pgx importer           NOT MET (Q27).
      The tests as written pass and are red where they should be. The
      phase-auditor added a file to internal/capture with no pgx import
      that called openSession(...).Exec("EXPLAIN ANALYZE DELETE …") and
      added a template from an init(); every test stayed green. The second
      half is fixed (a switch). The first is the package boundary, Q27.
  2 in CI, a write through a weakened path refused as read-only;
    statement_timeout on every session                  PASS in CI.
      TestASessionIsReadOnlyAtTheServer (cli job, run 43263355094): CREATE
      TABLE and CREATE ROLE refused, 25006; SHOW gives on, 10s,
      culprit-capture.
  3 the two capabilities from the shared fixture; an allowance narrows
    them; neither implies db.rows.read; none implies another   PASS.
      Red: making db.plan.read hold db.rows.read fails the Go test
      (phase-auditor). The Python test is weak: Python has no implication
      mechanism to test.
  4 demo database: capture yields the seeded table's index facts, the
    reader the declared ones; dropped by hand -> declared but missing;
    created by hand -> live but undeclared              PASS (live in CI).
      TestTheDemoDatabase (CI): live leading id, sku; head
      0002_seed_products; setup run twice. test_the_demo_migrations_
      declare_their_indexes: id, sku true; category, name, price false.
      TestIndexesDeclaredAndLive (CI): none at baseline, items.sku after
      DROP, items.category after CREATE, each intent_vs_configured.
  5 redaction of password=…, a Slack token, user:pass@host in Go and
    Python from shared cases, red without              PASS.
  6 Q26: a third net/http importer red; a client built another way red;
    the guard refuses a non-GET and a body, each red    PASS as written;
                                                         premise false (Q27).
      The phase-auditor added a file to internal/probe with no net/http
      import that took a client's transport through its fields
      (c.client.Transport.(methodGuard).next) and sent a DELETE: the
      server received it. Not naming a type does not stop a file using it.
  7 a latency reading without planned refused by Go, Python, the API PASS.
      Go and Python here, red on the old rule; the API test in CI's test
      job.
  8 isolation: accepted by both; a key one knows and the other does not
    fails a test                                       PASS.
      Red both ways (phase-auditor). Left, in LIMITS: an unknown top-level
      key is ignored by Go on purpose and refused by the API.
  9 from a fresh clone the quickstart starts with the demo's database,
    migrated and seeded                                PASS in CI (e2e).
  10 fault library unchanged and green; LLM_PROVIDER=none changes nothing;
    every PR check green                               PASS (fcd0b0a).

DELIBERATELY NOT BUILT (part 1's list)
  No statement timing, plan or statement budget. No walk change. No EXPLAIN
  of any kind sent. No row read by Culprit (alembic_version as before). No
  pg_stat_statements reset. No index created or dropped by Culprit. No
  change to Culprit's own database (the server-wide preload list aside,
  which LIMITS states).

GATES (local, Windows, Docker NOT running)
  lint, typecheck, lint-imports (6 kept), check-schema-drift,
  check-no-llm-imports, check-invariants, check-scan-coverage, cli-lint,
  check_security_doc (75), check_coupled_files --base origin/main   PASS
  go test ./... (cli)                                                 PASS
  pytest without a database: shared, scripts, manifests 1188 passed;
  extractors/python 37; frontend 19
  NOT RUN locally: every database-backed test, the Docker tests, the
  quickstart, e2e, the fault library. CI ran them all.

AUDITS
  invariant-auditor (fcd0b0a): CLEAN, 0 violations. Risks taken up: a
    RoundTrip or an aliased net/http in the two files (now red cases); the
    compose comment overstated what stays unchanged (corrected). Left: the
    synthetic demo password in the compose file; the user:pass@ pattern
    over-redacts; PERMISSIONS' role can read rows (documented).
  phase-auditor (fcd0b0a): NOT COMPLETE — criterion 1 NOT MET, Q26's
    premise false (both Q27); templates mutable (fixed); redaction missed
    SQL PASSWORD '…' (fixed); LIMITS overclaimed in two places (rewritten);
    CLAUDE.md stale (fixed). Left, in LIMITS: why: yes / 300 / a date is a
    string to Go and refused by the API; a second YAML document; an
    unknown top-level key. The fixes after fcd0b0a were not re-audited.

DECISIONS TAKEN HERE (for review)
  - leads_index (column-level, true and false) as the index predicate.
  - inventory-db's edge is background, so the order walk is unchanged.
  - The seed is 1,000,000 rows, 200 categories (reasons above).
  - pg_stat_statements is created by the demo's setup as superuser, not by
    its migrations as owner: the extension is not trusted.
  - The preload list is set explicitly and replaces the image's default.
  - A fixed synthetic password for the demo's database role.

IN THE PLAN, FOR CORRECTION
  - "One file opens database connections" and Q26's "no other file can
    name a client, a transport" are true of imports and not of use: Q27.
  - "Creating the extension ... by its migrations as their owner" cannot
    hold for pg_stat_statements, which only a superuser may create.

/CI
  run 43263355094 on fcd0b0a (pull_request) — SUCCESS, every job:
           lint, typecheck, cli (with the new database step: the three
           Docker tests PASS), test, migration-round-trip, self-check,
           kind-capture, fault-library, e2e (none), e2e (stub),
           narration-parity, build x5; publish, deploy skipped
  run on the report commit — see the PR's checks
  merge    origin/main = d785af4 is an ancestor of the branch: the branch
           is the merge result

LEFT OPEN
  - Q27 (blocking part 1's completion).
  - The readers' remaining splits (LIMITS).
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
