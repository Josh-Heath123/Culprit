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
| Current phase | **32.1, part 2 — Everywhere else** — status `gates red`. Committed as `2a851ee` (PR #25); its run 41916090503 was red on the `e2e` job alone: the quickstart's bootstrap container could not write `demo-services/.env` on a Linux runner. Fixed in the justfile (§5, CI), awaiting commit and a new run. Every other job was green, `self-check` and its SARIF upload included. **Not complete** until a run is green on the merge result. |
| Previous phase | **32.1, part 1 — The system, on the Investigation screens:** reviewed 2026-11-04 by the architecture session, and the look approved by Malcolm on the screenshots. Complete once PR #24 (`bd29351`) is green and merged. Decisions and Malcolm's four changes are at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Every merge to `main` runs `deploy` (PR #19 `a3f110a`, PR #20 `4f69ab3`), and it is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-32.1-part-2`, cut from `origin/main` after PR #24 merges; its first commit is this brief. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** Open questions are in §3. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q16 | **Where did the VM remediation land?** Is SSH access to `culprit-vm` restored, and has anything changed on it since 2026-09-12? The answer decides whether Phase 31.2's README may link `culprit.co.za`, and the VM must deploy green before Phase 33. | 2026-11-03, architecture | **Phase 33, the phase after 32.1:** the VM must deploy green before it starts. (Phase 31.2 shipped with no live link.) |

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
| 32, part 2 | The investigation in the control plane | **complete** | **Signed off 2026-11-04** (architecture session), subject to the quickstart verification on `main` recorded in §5. Merged via PR #23 (`a22da56`). Decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — "How Phase 32 is run", then "Part 2 — the investigation in the control plane" at the end of the section, which holds the work order, the criteria and what not to build. Branch `phase-32-control-plane`. Order: the carried-in items first (the token grant, the symptom's attestation, untested versus unexplored branches; then the last admin), then storage, the API, the view, the correlation engine's removal, and the quickstart, README and LIMITS last. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.1, part 1 | The system, on the Investigation screens | **complete** (PR #24 merged, run 41875987970 green) | **Reviewed 2026-11-04** (architecture session); look approved by Malcolm on the screenshots. PR #24 (`bd29351`). Decisions at the end of Phase 32.1 in `DIAGNOSTIC_PLAN.md`. |
| 32.1, part 2 | Everywhere else | **gates red — fix awaiting commit** | 2026-11-04: `2a851ee`, PR #25; run 41916090503 red on `e2e` only (quickstart bootstrap, Linux bind-mount ownership), fixed in the justfile, awaiting commit and CI. SARIF upload accepted (`self-check` green). Screenshots of every route in `docs/review/phase-32.1-part2/`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32.1 — "Malcolm's review of the screenshots" and "Part 2 — everywhere else" at the end of the section, which hold the four review changes, the work order, the criteria and what not to build; field 14 as refined applies. Requirements: `docs/PRODUCTISATION.md` §2, §4, §7 and §8. First confirm with `gh` that PR #24 is merged with CI green; if not, stop. Follow the work order: the review changes first, the fresh-eyes review last. Branch `phase-32.1-part-2`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
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
Phase:        32.1, part 2 — Everywhere else
Branch:       phase-32.1-part-2, cut from origin/main = 5a7acfe (PR #24's
              merge); first commit 8006010, the part 2 brief. origin/main
              has not moved, so the working tree is the merge result.
Run:          2026-11-04, /next. Precondition checked with gh: PR #24
              merged, and its pull_request run 41875987970 (on the merge
              ref) concluded success on every job, deploy skipped. (It was
              merged while the frontend build was still running; the run
              was watched to the end before any work began.)
Status:       IMPLEMENTED, NOT COMPLETE. Every part 2 criterion that can be
              run locally is met; both audits and the fresh-eyes review ran
              and their findings are fixed or listed below. Not committed
              (the human commits); CI NOT RUN — and two criteria live only
              in CI: the e2e job green on the merge result, and the SARIF
              upload working.
Commit msg:   ..\phase-32.1-part2-commit-msg.txt (shared/uv.lock not staged).

GATES (local, Windows, final tree)
  just lint / typecheck / lint-imports      PASS (4 contracts kept, none widened)
  just check-schema-drift                   PASS
  just check-no-llm-imports                 PASS
  just check-invariants / check-scan-coverage  PASS
  just check-frontend-tokens                PASS  63 files — all of frontend/src
  just cli-lint / cli-build                 PASS
  just test                                 PASS  api+scripts+shared 1080 / 4 skipped
                                                  (pre-existing), worker 65, mcp 21,
                                                  extractors 31, Go all ok. (1091 in part 1:
                                                  13 alias contrast pairs retired, 2 gate
                                                  tests added.)
  frontend: tsc -b, oxlint, npm test, build PASS  (npm test 13/13; oxlint 1 pre-existing
                                                  warning, ui/badge only-export-components)
  npm audit --audit-level=high              PASS  0 high, 0 critical
  just e2e vs a quickstart of this tree     PASS  4/4 (export identical to the tree,
                                                  file for file)
  check_coupled_files --base origin/main    PASS
  culprit check --fail-on=breaks_request_path / LLM_PROVIDER=none   exit 0 / 0
  just fault-library                        NOT RUN — no CLI or walk change in part 2
  /ci                                       NOT RUN — needs the human's commit and push

PART 2 CRITERIA
  The four review changes, each tested    MET.
    1 dates: lib/datetime.ts, `4 Nov 2026, 18:18`; unit test (5 cases);
      the token gate refuses toLocale*String/Intl.DateTimeFormat anywhere
      else (shown red on NotFound.tsx by the auditor); the tour asserts the
      format on screen. Date-only `4 Nov 2026` (ingest keys) and time-only
      axis labels come from the same formatter.
    2 investigation id out of the header: the tour asserts it.
    3 hypothesis labels: lib/hypotheses.ts, one map; its test reads
      shared/tests/investigation_conformance.json and fails on an unlabelled
      kind (auditor added `queue_backlogged` → red); label above, kind in
      mono beneath, in the view and "could not check".
    4 flags: lib/prose.ts splits them out (4 tests); components/ui/prose
      renders <code> nowrap; the tour asserts white-space: nowrap on
      `--reference`.
  Token gate over all of frontend/src      MET. components/ui included
      (dialog's top-[20%] gone). Shown red by a deliberate raw colour in
      SettingsUsers.tsx (text-[#9aa3b5] → 2 violations, exit 1), and by the
      auditor in separator.tsx, NotFound.tsx and PostmortemList.tsx. The
      shadcn aliases are deleted from index.css; every route uses the token
      names. Contrast test: every text token on every surface, each status
      on its tint, white on the blue fill.
  e2e job green in CI on the merge result  NOT RUN in CI. Job `e2e` in
      ci-cd.yml: npm ci, oxlint, npm test, Playwright Chromium, `just
      quickstart`, `just e2e`; screenshots kept as an artifact; deploy now
      needs it. Locally 4/4 against a quickstart of this exact tree.
      A Linux-only defect the phase audit found (D1: the bootstrap ran as
      root and wrote infra/.env.prod 0600, unreadable on a runner) is fixed
      (--user) and the fix was run, but only on Windows; CI is its test.
  npm audit: no high or critical           MET. nanoid, source-map-js, vite
      cleared by `npm audit fix` in the lockfile (vite 8.3.5). 2 low and 4
      moderate remain, all in dev tools (shadcn CLI via deepmerge,
      openapi-typescript via minimatch); each fix is a major downgrade. The
      lockfile changed more than the brief implied: shadcn 4.16.1 → 4.23.0
      (in its ^4 range) dropped ~70 transitive packages and added 7
      (@modelcontextprotocol/core|server, @shadcn/registry, cn, socks,
      smart-buffer, an optional rolldown binding), all dev-only; no
      package.json dependency changed; the runtime set is unchanged.
  SARIF upload                              NOT RUN in CI. Restored in the
      self-check job (github/codeql-action/upload-sarif@v4, category
      culprit), artifact kept. Code scanning's default setup is
      "configured" and the repository is public, so it should be accepted;
      if it is refused, the step must be stopped and Malcolm asked, per the
      brief — not left failing.
  README screenshots from the suite        MET. docs/screenshots/ (4) are
      byte-identical to the final tour run's output; the README shows the
      interface and links no video.
  Video materials committed                 MET. docs/video/script.md,
      storyboard.md, checklist.md (§7's five parts). Not recorded.
  Field 14 as refined                       MET locally, with one gap.
      Every surviving route at 375/768/1280/1920 — 14 screens, 56
      screenshots in docs/review/phase-32.1-part2/ — each checked for
      horizontal overflow, keyboard focus reaching the content (or the open
      dialog) with a visible outline (mutation: removing the global focus
      outline turned it red on every route), and no console error or failed
      request. The main journey by keyboard alone. A member meets "This page
      is for admins". LLM_PROVIDER=none: nothing reads it; the interface is
      complete and says plainly that no prose summary is generated. GAP: an
      incident's detail panel, and the postmortem editor opened from an
      incident, are never rendered — nothing creates incidents any more,
      so no stack has one.

WHAT WAS BUILT
  - Review changes as above.
  - Every route on the system: one Page shell + AppHeader (glass; menu
    below 768, account actions below 1024), Brand, Standalone for sign-in,
    404 and admins-only; incidents (history) with a keyboard-operable
    timeline, chart colours as token classes, the timeline scrolling inside
    its card below ~576 px; postmortems list and editor (two-step delete,
    embedding status as word + icon); settings services and users (native
    token Select, responsive rows); change-password and command-palette
    dialogs titled for assistive technology. States: skeletons, empty and
    error panels (components/ui/states) on every data view.
  - `/` now lands on investigations; the incident history moved to
    `/incidents` (the fresh-eyes review: signing in landed on a retired,
    empty page).
  - False copy removed: "Culprit is watching. Incidents appear here as soon
    as one opens" (nothing opens incidents now), "accepting one changes
    correlation on the next tick" (the correlation engine is gone), the
    narrator described as present (README D8), the stale self-check CI
    comment (continue-on-error, `just self-check-sarif`), the LIMITS SARIF
    section.
  - Deleted: Nav.tsx, ErrorState.tsx, screenshots.spec.ts (folded into the
    tour), the shadcn aliases.
  - Frontend unit tests on Node's own runner (`npm test`), no new dependency.
  - CI: the e2e job; the SARIF upload; deploy needs e2e.
  - The quickstart no longer prints the admin password when CI is set (a
    public repository's logs are readable by anyone).
  - Docs: README (interface screenshots, testing rows, D8, future work),
    LIMITS (time zone, narrow timeline, e2e needs the stack + rate limit,
    dev-only advisories, SARIF rewritten, the symptom edge resting on the
    root's reading), docs/video/, CLAUDE.md status.

DELIBERATELY NOT BUILT (do-not-implement)
  No backend change of any kind (api/, worker/, cli/, shared/ untouched);
  no control that opens an investigation; no new component, chart,
  animation or CSS library (the one new frontend devDependency remains
  part 1's Playwright); no change to what the walk decides — including its
  wording, which is why the items under LEFT OPEN are not fixed here; no
  video recorded.

AUDITS AND THE FRESH-EYES REVIEW
  invariant-auditor: clean on all seven invariants. Defects fixed: the gate
    test required a gitignored, generated file (would have failed pytest in
    CI); the e2e failure artifact uploaded Playwright's error-context.md,
    whose page snapshot includes password field values — now screenshots
    only; the quickstart printed the admin password into CI logs. Risks
    fixed: deploy now needs e2e; the README's contrast claim stated
    precisely; a stale badge comment.
  phase-auditor: NOT COMPLETE pending CI, as expected. Fixed: D1 (above),
    D2 status docs (this report, CLAUDE.md, README future work), D3/D4
    counts and comments, D5 copy that promised incidents, D6 partly (the
    command palette, change-password dialog and an existing postmortem are
    now checked at four widths; incident detail cannot be).
  fresh-eyes review (an agent that had seen none of the work, as recruiter
    and senior engineer). Fixed: `/` landing on the retired page; "admin ·
    admin" in the header (role is now a badge); "reproduced — yes" beside
    "Not reproduced" (the symptom card now says the symptom was not
    replayed and that "reproduced" is about the root's reading); the D8
    narrator text; stale self-check comment; the stale LIMITS SARIF
    section; comments naming the deleted Nav.tsx; the investigation list
    moved onto Page; e2e seeding counts; comments citing a meeting rather
    than a reason; the symptom edge resting on the root's reading,
    documented in LIMITS.

LEFT OPEN (for the architecture session and Malcolm)
  - The walk's own text, which part 2 may not change: a rubric reason says
    "…which is Phase 34", the complete statement reads as machine prose
    ("order-service fails because of auth:…; the readings rule out the
    alternatives they reached"), and a partial statement quotes the raw
    kind. A wording pass on cli/internal/isolate is worth its own brief.
  - The recorded partial-with-boundary investigation's environment is
    "test" (it comes from the isolate test world), and it shows in the
    README's list screenshot.
  - The e2e job rebuilds every image separately from the build job, so it
    is the slowest job in the pipeline.
  - The README still says "Go 1.25+" while CI builds with 1.27 only; the
    1.25 floor is never exercised.
  - DIAGNOSTIC_PLAN.md D8 still describes `LLM_PROVIDER=none` as "a CI
    job"; no such job exists since the narrator was removed. The plan is
    the architecture session's to amend.
  - docs/review/phase-32.1-part2/ is 4.7 MB of 56 PNGs; part 1's set is
    there too. Whether review screenshots stay in the repository after
    review is a call to make.
  - The tour is one long test with soft assertions; an early hard failure
    hides the routes after it. Each run leaves an `e2e-member-…` user in
    the stack (LIMITS says so).

CI, 2026-11-04 (/ci)
  commit   2a851eecfdbcce516f21522010b9e6b46a68d6fd (PR #25)
  run      41916090503  https://github.com/Josh-Heath123/Culprit/actions/runs/41916090503
  Merge result: origin/main = 8006010, the branch's parent, so 2a851ee IS
  the merge result (fast-forward; nothing to merge). Local gates re-run on
  it: all PASS (lint, typecheck, lint-imports, schema-drift, no-llm,
  invariants, scan-coverage, frontend-tokens, cli-lint, coupled files,
  just test, tsc, oxlint, npm test, npm audit, culprit check exit 0,
  LLM_PROVIDER=none exit 0).
  Jobs: success lint, typecheck, cli, test, migration-round-trip,
    self-check, kind-capture, fault-library, build x5; skipped deploy;
    FAILURE e2e.
  Verdict: RED.
  Cause (test-triage, from the failed step's log): step "Quickstart",
    `sh: 17: cannot create /demo-services-env/.env.new: Permission
    denied`. The compose `bootstrap` service runs as the api image's
    `app` system user and writes demo-services/.env through a bind mount
    of a directory the runner user owns. Docker Desktop does not enforce
    the ownership, so it never showed on Windows. Not new in this commit
    (the mount predates it); this was the first quickstart on a Linux
    host, so any Linux user's fresh `just quickstart` hit it too.
    Playwright never ran.
  Fix (uncommitted, staged): the justfile runs that service with
    `--user "$(id -u):$(id -g)" -e HOME=/tmp`, as it already ran
    bootstrap_env.py. Locally, from a clean export of 2a851ee plus the
    fix: just quickstart exit 0 (wrote demo-services/.env, printed
    /investigations/inv-1dd6b3d7d19b5a04), just e2e 4/4. That proves no
    regression on Windows only; the Linux proof is the next CI run.
  SARIF: self-check concluded success with the upload step, so code
    scanning accepted it. Nothing to ask Malcolm.
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
