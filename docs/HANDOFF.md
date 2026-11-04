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
| Current phase | **32.1, part 1 — The system, on the Investigation screens** — status `implemented, awaiting commit and CI`. Every part 1 criterion met locally and both audits' findings fixed (§5); the commit, the CI run on the merge result and Malcolm's review of the screenshots (`docs/review/phase-32.1-part1/`) are next. **Not complete** until that CI run is green. |
| Previous phase | **32 — Fault isolation and the Investigation: complete** (parts 1 and 2), signed off 2026-11-04 by the architecture session, subject to one verification: `just quickstart` from a fresh clone of `main` (`a22da56`), which part 2 could not finish on its final tree. Part 2 merged via PR #23 (`a22da56`). Decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Every merge to `main` runs `deploy` (PR #19 `a3f110a`, PR #20 `4f69ab3`), and it is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-32.1-interface`, cut from `origin/main` = `a22da56`; its first commit is the Phase 32 sign-off. Do not stage `shared/uv.lock`. |
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
| 32.1, part 1 | The system, on the Investigation screens | **implemented, awaiting commit and CI** | 2026-11-04: all part 1 criteria met locally (§5), both audits run and their findings fixed; not committed, no CI run yet. Screenshots for Malcolm in `docs/review/phase-32.1-part1/`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32.1 — all 17 fields, read with "Carried in from Phase 32" and "How Phase 32.1 is run" at the end of the section, which win where they differ. Requirements: `docs/PRODUCTISATION.md` §2 and §4. Start only once §5 records the part 2 quickstart verification on `main` as passed. **Part 1 only:** the carried-in items first (connection kinds, the browser test and its runner, the CLI's partial-diagnosis wording), then the tokens and the component set, then the investigation list and view. No other route is restyled. End with the screenshots at four widths in the run report, for Malcolm. Branch `phase-32.1-interface`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32.1, part 2 | Everywhere else | not started | Written after Malcolm reviews part 1's screenshots; his notes go into it. |
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
Phase:        32.1, part 1 — The system, on the Investigation screens
Branch:       phase-32.1-interface, cut from origin/main = a22da56 (first
              commit 6a6f6c3, the Phase 32 sign-off). origin/main has not
              moved, so the working tree is the merge result.
Run:          2026-11-04, /next. Precondition met: the part 2 quickstart
              verification on main is recorded as PASS (git log -p, the
              previous §5).
Status:       IMPLEMENTED, NOT COMPLETE. Every part 1 criterion met
              locally; both audits run and every finding fixed or listed
              below. Not committed (the human commits); CI NOT RUN. The
              phase is complete only when the run on the pushed commit's
              merge result is green — and part 2 waits for Malcolm's review
              of docs/review/phase-32.1-part1/.
Commit msg:   ..\phase-32.1-part1-commit-msg.txt (shared/uv.lock not staged).

GATES (local, Windows, final tree)
  just lint / typecheck / lint-imports       PASS (4 contracts kept, none widened)
  just check-schema-drift                    PASS
  just check-no-llm-imports                  PASS
  just check-invariants                      PASS
  just check-scan-coverage                   PASS
  just check-frontend-tokens (new)           PASS  10 files, tokens only
  just check-migration-round-trip            PASS  (no migration in this part)
  just cli-lint / cli-build                  PASS
  just test                                  PASS  api+scripts+shared 1091 passed /
                                                   4 skipped (pre-existing), worker 65,
                                                   mcp_server 21, extractors 31, Go all ok
  just fault-library                         PASS  7/7 (re-recorded; see below)
  just e2e (new) vs. a quickstart stack      PASS  4/4, twice in a row
  frontend: npx tsc -b, npm run build        PASS  (oxlint: 2 pre-existing warnings
                                                   in ui/badge, ui/button)
  check_coupled_files --base origin/main     PASS
  culprit check --fail-on=breaks_request_path  exit 0
  LLM_PROVIDER=none culprit check              exit 0
  /ci                                        NOT RUN — needs the human's commit
                                             and push.

PART 1 CRITERIA ("How Phase 32.1 is run")
  Carried in: connection kinds closed     MET. shared/tests/
      connection_kind_conformance.json is read by Go (cli/internal/model/
      conformance_test.go) and Python (shared/tests/test_graph.py), and by
      api/tests/test_manifest_environments.py against the migration's
      ck_connections_kind literal (added after the invariant audit found
      the database unbound). The Go loader refuses an unknown kind (exit 2,
      naming component and edge). Shown red first: with `queue` still in
      the root culprit.yaml, Go TestEveryShippedManifestLoads and the
      Python loader both failed; `message` turns them green.
  Carried in: browser test + runner       MET. frontend/e2e/ with
      @playwright/test 1.64.1 (the one dependency field 11 allows; only it,
      playwright and playwright-core enter the lockfile), `just e2e`
      against a running quickstart. Part 2's 13 checks are the first
      journey; every test fails on any console error or failed request
      except the ones a deliberate error path names. NOT in CI yet — that
      is part 2.
  Partial diagnosis wording               MET (after the phase audit's D1).
      CLI: "Diagnosis (PARTIAL) — where the walk stopped…", "stopped at",
      "could not check", no fix, and the boundary edge printed
      -[stopped_at]-> not -[caused_by]->. The walk's statements no longer
      say "because of" or "The cause is inside" for a partial. View and
      list: "Walk stopped at", "Could not check", no root marker, no
      suggested fix, edge labelled "walk stopped at". Tests: diagnose_test
      (diagnosis block), isolate TestABoundaryWithUntestedAlternatives…
      (whole text output, mutation-checked: red without the relabel), e2e
      over three partial investigations (whole <main>, tree expanded).
  Every token pair meets WCAG 2.2 AA       MET. scripts/tests/
      test_design_tokens.py reads index.css itself, builds the pairs from
      token names (every text token × every surface, glass composited over
      the page, each status on its tint, the shadcn aliases), lowest pair
      5.07:1; a test fails if a new text token escapes the pairing.
      Mutation: --fg-subtle #5a6070 → 5 failures.
  Screens style through tokens only        MET. scripts/check_frontend_tokens.py
      (just + CI step), scoped to the two routes, components/investigation,
      AppHeader, ui/card and ui/status. Refuses hex/colour functions,
      palette colours, arbitrary values and properties, CSS-variable
      shorthand, colour opacity modifiers, any inline style, colour props.
      Mutation: `text-rose-400` in InvestigationView.tsx → exit 1, named
      line; plus a real-file mutation test and one case per rule.
  LLM_PROVIDER=none complete               MET. Nothing reads the variable since
      part 2; the quickstart stack has no model key; the suite passes; the
      diagnosis card says plainly "no model wrote it. Culprit does not
      generate prose summaries."
  Screenshots at 375/768/1280/1920         MET. docs/review/phase-32.1-part1/:
      list, complete (edge expanded), partial, each at four widths, taken
      by frontend/e2e/screenshots.spec.ts, which also fails on horizontal
      overflow at any width. The auditor's own run produced byte-identical
      files.

WHAT WAS BUILT
  - Tokens (frontend/src/index.css): midnight surfaces 0–3, glass + scrim,
    fg / fg-muted / fg-subtle, lines, electric blue (brand, brand-fill +
    white on-fill), cantaloupe (highlight: the brand mark and a complete
    diagnosis's root only), the four verdicts and four severities as fg/
    tint/line sets, text-2xs, radii, shadows, blur. shadcn names kept as
    aliases so un-redesigned routes render through the same values. Global
    :focus-visible, prefers-reduced-motion, and ligatures off so `->` in a
    subject is never drawn as an arrow (found in the screenshots).
  - Components: ui/card (solid/raised/glass), ui/status (Verdict, Severity,
    Diagnosis badges: colour + icon + word), badge/button/input/skeleton/
    dialog/tooltip moved onto tokens, DialogTitle/DialogClose exported,
    layout/AppHeader (glass; links fold into a menu below 768 px, account
    actions below 1024 px).
  - Screens: InvestigationList and InvestigationView redesigned —
    diagnosis card (root or "walk stopped at", rubric as four booleans,
    could-not-check), fault tree on a solid surface with the boundary
    marked, symptom card (glass), hypotheses in four groups; skeleton,
    empty and error states; a 404 says the id is not stored and offers no
    retry (and is not retried).
  - CLI: ConnectionKind closed set; partial wording in isolate and report.
  - Fixtures: api/tests/data/investigations re-recorded from the fault
    library (new wording), plus partial-with-boundary.json from the isolate
    test world (no fault-library case yields a partial with a fault tree).
  - Docs: LIMITS (three sections), UPGRADING (connection kinds), CLAUDE.md
    status, docs/review/phase-32.1-part1/README.md.

DELIBERATELY NOT BUILT (field 17 and the part 1 boundary)
  No other route restyled (they inherit the shared tokens/components only);
  no backend feature or endpoint; no e2e job in CI, no SARIF upload, no
  video materials, no README screenshots, no fresh-eyes review — all part 2.

AUDITS
  invariant-auditor: clean on all seven invariants. One finding fixed: the
    shared kind fixture did not bind the database CHECK (test added,
    mutation-checked). Risks fixed: Playwright trace (would record the
    password and bearer header) turned off; ui/card and ui/status added to
    the gate's scope; an empty scope directory is now an error; the e2e
    default base URL matches the recipe; `just e2e` undoes compose's $$
    escaping. Risk fixed: the new partial-with-root branch now has a test.
  phase-auditor: NOT COMPLETE on criterion 3 (D1: a partial
    investigation's boundary edge still read "caused_by"/"caused by" in
    the CLI tree and the web tree). Fixed as above. Other findings fixed:
    D2 gate bypasses (CSS-variable shorthand, arbitrary opacity, any
    inline style, colour props — each a test case); D3 Radix data-/aria-
    variants no longer false positives; D4 404 retry; D5 mixed line
    endings in three appended files. Every other criterion MET by its
    execution.

LEFT OPEN (for the architecture session and Malcolm)
  - Orange marks a complete diagnosis's root (the "ROOT" label and the tree
    node). Field 4 says orange is never used where it could read as a
    status; the root is a boundary marker, not a verdict, and it always
    carries an icon and the word — but whether that reads as status is
    Malcolm's call on the screenshots.
  - The e2e suite needs a running quickstart and is not in CI; part 2 adds
    the job. Sign-in is limited to 10/minute per address, so the suite
    signs in five times per run and moves by clicking.
  - ui/dialog.tsx keeps a pre-existing `top-[20%]`, outside the gate until
    part 2 widens SCOPE to components/ui.
  - npm audit reports 3 high advisories (nanoid, source-map-js, vite
    8.2.0–8.2.2) that predate this branch (present with package.json at
    HEAD); for the standing advisories task, not this phase.
  - The stored field is still `root_subject` for partial diagnoses; only
    its presentation changed (LIMITS says so).
  - Investigations stored before this phase keep their older partial
    wording (they are final).
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
