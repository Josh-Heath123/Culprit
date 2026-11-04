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
| Current phase | **31.2 — Present what works** — status `in progress`, **awaiting the human's commit and then `/ci`**. README rebuilt, fresh-clone run and frontend truth pass done, both audits run and their findings fixed, every local gate green (§5). Not `complete`: CI on the merge result has not run. Brief in §4. |
| Previous phase | **31.1 — Close the probe loop: complete**, signed off 2026-11-04 by the architecture session. Merged via PR #20 (`4f69ab3`); CI green on every job on the merge result (run 41789133416), with `.trivyignore` empty. Decisions on its open items are at the end of Phase 31.1 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Every merge to `main` runs `deploy` (PR #19 `a3f110a`, PR #20 `4f69ab3`), and it is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-31.2-present-what-works`, cut from `origin/main` = `4f69ab3`; its first commits are the 31.1 record-keeping and the 31.1 sign-off. Do not stage `shared/uv.lock`. |
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
| 31.2 | Present what works | **in progress — built and audited, CI not run** | **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. **Go-ahead 2026-11-04:** the branch `phase-31.2-present-what-works` exists, cut from `origin/main` = `4f69ab3`. Read Phase 31.2 in the plan including "Carried in from Phase 31.1". **Review 2026-11-04 (before CI):** justfile fix ratified with one change (types generated from the lockfile, as CI does); criterion 4 refined; five README and LIMITS corrections to make on this branch before merge — `DIAGNOSTIC_PLAN.md`, end of Phase 31.2. The last-admin guard is Phase 32's third item. |
| 32 | Fault isolation and the Investigation | not started | Read `DIAGNOSTIC_PLAN.md` Phase 32, including "Added 2026-11-03". The full brief is written when 31.2 is complete. Its first two items are carried in from 31.1 (evidence renders a CONFIGURED fact as its shape; the catalogue mirror is generated). |
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
Phase:        31.2 — Present what works
Branch:       phase-31.2-present-what-works, cut from origin/main = 4f69ab3
              (its first commits are the 31.1 record-keeping and sign-off).
              origin/main has not moved, so the working tree is the merge
              result.
Run:          2026-11-04, /next. Phase 32 NOT started.
Status:       IN PROGRESS — built, truth-passed, audited, local gates
              green. CI on the merge result NOT RUN: it needs a commit,
              and the human commits. Criterion 5's GitHub half needs the
              push too.
Committed:    NO, by protocol — staged, message written; the human commits.

WHAT WAS BUILT
  README.md        rebuilt to PRODUCTISATION.md §6, centred on the CLI:
                   problem/users/value; real captures; key features; how it
                   works (planes, facts, subjects, divergences, readings)
                   with two Mermaid diagrams; the stack by role; D1-D8 in
                   plain language; installation (CLI from source — no
                   release exists, so no curl|sh — and the quickstart);
                   a five-minute end-to-end tour; testing; structure;
                   limits; future work as plans; author/licence. No video
                   link, no screenshots of the web UI (described, not
                   showcased), no culprit.co.za link (Q16 open).
  scripts/render_captures.py + `just readme-captures`
                   regenerates docs/captures/{check,diff,probe}.svg from
                   real runs: `check` on cli/testdata/demo; `env capture` x2
                   + `diff` and `probe` against a synthetic project and a
                   throwaway 127.0.0.1 HTTP server it starts itself.
                   Standard library only; subject targets built with
                   culprit_model.subjects.build; refuses to write a capture
                   if an extractor crashed. Tested in
                   scripts/tests/test_render_captures.py (7).
  extractors/{python,node}/README.md
                   install from the clone path (not on PyPI/npm — field 17);
                   culprit.co.za link replaced with the GitHub repo.
  docs/PROBES.md, docs/UPGRADING.md, docs/INSTALL.md
                   PROBES and UPGRADING touched in 31.1; INSTALL needed no
                   change (its ghcr visibility note is accurate for forks).

DEFECTS FOUND AND FIXED
  Fresh-clone setup
  1. `just quickstart` from a fresh clone DID NOT BUILD: the frontend image
     needs src/lib/api-types.generated.ts, which is gitignored; CI
     generates it on the runner, the recipe never did. It only ever worked
     from a checkout that already had the file. Fixed in the justfile:
     schema dumped from the api image under `env -i` with the same
     placeholder values `just generate-types` uses (no .env.prod value can
     reach the file — invariant-auditor's recommendation; byte-identical
     output verified), types generated in a node:22-alpine container with
     the lockfile's openapi-typescript@7.13.0. NOT IN FIELD 5's file list
     — see "For the architecture session".
  2. README demo output needed `npm ci` in extractors/node (without it: 4
     divergences / 19 gaps, not 5 / 17). README now says so.
  3. README's getting-started culprit.yaml declared no extractors, so a
     user got artefact readers only. The tour now declares one.
  4. extractors/*/README.md told users to install from PyPI/npm, where
     nothing is published.
  5. README promised the quickstart shows "an incident with a root-cause
     narrative"; without VOYAGE_API_KEY and an LLM key no narrative is
     ever written. README, the quickstart's closing message and the
     incident panel's pending copy now say so; LIMITS records it.
  6. README said the fault fires "about 75 seconds in"; the recipe says 90.
  Frontend truth pass (32 scripted steps, admin and member, every route,
  console and network read on each — harness in the scratchpad, not
  committed)
  7. The only admin could demote or disable themselves from Settings ->
     Users: one click, zero admins, every admin page 403 (reproduced).
     Your own row now has no role/disable control. The API still allows
     it — LIMITS, and see below.
  8. Deleting a postmortem navigated to a list that still showed it (the
     editor bypassed the hook that invalidates the list).
  9. A member's dashboard was blank: the timeline's lanes came from
     admin-only /model (403), so no lanes and no bands, while the header
     counted the incidents. Lanes now come from the incidents for a
     member, and the admin-only request is not sent.
  10. A member reaching /settings/users or /settings/services by URL got
     the admin forms, every control of which could only 403. New
     RequireAdmin route guard says "This page is for admins."
  11. The newest closed incident's band ran past the time axis under the
     detail panel and could not be clicked (closed_at missing from the
     domain).
  12. Seven mutations on the Services and Users pages failed silently on
     error; each card now shows the error.
  13. A wrong current password in Change password logged you out (any 401
     cleared the session). It is now a message in the dialog.
  14. scripts/render_captures.py hand-formatted subject URIs; the subject
     lint caught it in `just test`; now uses the builder.

ACCEPTANCE CRITERIA (field 14)
  1. Every README setup/usage command run from a fresh clone      PASS
     Clone of the public repo (4f69ab3) in C:\Users\flosh\
     culprit-freshclone-31.2, outside %TEMP% (see Environment), with this
     branch's changed files copied in. Run literally, in order:
       just cli-build; (cd extractors/node && npm ci);
       export PATH=...; cd cli && culprit check -f testdata/demo/culprit.yaml
         -> 5 divergence(s), 17 gaps, exit 1 (byte-identical to the
            working repo's run)
       the tour: export CULPRIT_HOME; the four heredocs; `culprit check`
         -> No divergences, 16 facts, exit 0; two `env capture`s and
         `culprit diff` -> 1 divergence, PAYMENTS_API_KEY
         breaks_request_path, exit 1; http.server + three `culprit probe`s
         -> /health PASS, /orders FAIL (404), expected_source
         api/openapi.json
       just quickstart (fixed recipe, run twice) -> every step, admin
         created, stack healthy, incidents within minutes
     Two substitutions for THIS MACHINE, not the README: compose project
     `culprit-freshclone` (the default name would reuse an existing volume
     with different passwords) and the dashboard on 127.0.0.1:8088 (an
     Apache inside WSL holds :80). Windows-only: `python` for `python3`,
     as the README now says. phase-auditor re-ran the CLI and tour
     commands independently from its own clone: same results.
  2. Every README image produced by a committed command           PASS
     `just readme-captures`; the auditor regenerated them in an isolated
     copy: check/diff text identical, probe differs only by port.
  3. phase-auditor finds no unsupported claim                     PASS after
     fixes — its first pass listed seven README claims; all corrected
     (least-privilege wording vs the anomaly-detector read grant and two
     role reuses; D1's 2026-11-03 amendment; Trivy blocks only fixable
     findings; an unsupported "two rounds, five false positives" story
     inherited from the old README, removed; `just test`'s real scope;
     dep.version/config.present caveats; minor wording). Not re-audited
     after the fixes — each was checked against the source it cites.
  4. Every route: zero console errors, zero failed requests, no
     control does nothing                                         PASS on
     every success path, admin and member. NOT TESTABLE AS WRITTEN on
     error paths: a deliberate 401/404/409 always produces Chromium's
     "Failed to load resource" console error, and every 204 (DELETE,
     reset-password) is reported by the browser as net::ERR_ABORTED after
     the server's clean 204 (verified with curl and by the effect landing).
     "Generate now" without keys re-queues a job that fails in the worker:
     the control works and says honestly why nothing appears.
  5. Both diagrams render on GitHub                               local PASS
     (mermaid 11.4.1, both render, screenshots read); GitHub NOT RUN
     until pushed.
  6. culprit.co.za not linked                                     PASS
     (README, INSTALL, PROBES, LIMITS, both extractor READMEs). Q16 open.

CARRIED IN FROM 31.1
  probe.config.present and probe.dep.version, run inside order-service
  against the demo stack:
    config.present INVENTORY_SERVICE_URL -> inconclusive, measured
      is_set=true ("no INTENT fact declares ... required")
    config.present CULPRIT_NOT_A_REAL_KEY -> inconclusive, is_set=false
    dep.version fastapi (with and without expect_version) -> refused,
      repo.read not granted (and the demo declares no packages: command)
  Neither reaches a verdict on the demo, so the README shows neither and
  says what each needs. (The auditor separately got config.present
  PASS/FAIL against a process environment that declared the key.)

AUDITS
  invariant-auditor   CLEAN (before the last round of fixes). Its three
                      risks: the schema dump saw real secrets — FIXED with
                      env -i; `npx -y openapi-typescript@7.13.0` fetches
                      without the lockfile's integrity hash — open, small;
                      RequireAdmin shows "for admins" if the current-user
                      request errors — client-side only, server enforces.
  phase-auditor       1 PASS (commands; report now written), 2 PASS,
                      3 FAIL -> fixed, 4 FAIL -> two controls fixed
                      (change-password logout, "Generate now" copy), rest
                      is the wording problem above, 5 local only, 6 PASS.

GATES (working tree = merge result), after the last edit
  lint, typecheck, lint-imports, check-schema-drift         PASS
  check-no-llm-imports, check-scan-coverage, check-invariants,
  coupled files --base origin/main, cli-lint                PASS
  just test: api 898 / 4 skipped, worker 101, mcp 21,
    go test ./..., extractors py 31 / node                  PASS
  frontend tsc -b and npm run build                         PASS
  just self-check: no divergences, 1023 facts / 451 subjects PASS
  LLM_PROVIDER=none self-check                              PASS
  check-migration-round-trip, cli-test-docker/kind          NOT RUN
    (no migration, no CLI change this phase; both CI jobs)
  CI on the merge result                                    NOT RUN

ENVIRONMENT — particular to this machine
  - Port 80 is held by an Apache inside WSL (also in 31.1).
  - A clone under %TEMP% cannot run the quickstart from Git Bash: it maps
    %TEMP% to /tmp and Docker reads that as its own VM's /tmp. Cost two
    failed runs; in LIMITS because a Windows user could hit it.
  - infra/.env.prod is still the pre-Phase-28 file (31.1).
  - Leftovers, for the human to remove: the culprit-freshclone stack
    (`docker compose -p culprit-freshclone ... down -v`) and its clone
    C:\Users\flosh\culprit-freshclone-31.2; C:\Users\flosh\
    culprit-extinstall-test (an extractor-install test; deleting it was
    denied to this session); the auditor's C:\Users\flosh\culprit-audit-312.

DELIBERATELY NOT BUILT (field 17)
  No restyle, no design system, no new UI feature (RequireAdmin, the
  "you" badge, member lanes and the inline errors make existing behaviour
  honest), no new dependency (openapi-typescript is the lockfile's
  version; Playwright and mermaid ran from the scratchpad only), no video,
  no publication.

FOR THE ARCHITECTURE SESSION
  - Field 5 does not list the justfile, but the quickstart did not build
    from a fresh clone, and fixing that in the README alone would have
    meant telling a new user to install uv and Node, contradicting the
    quickstart's one promise. Fixed in the recipe; wants ratifying.
  - The API lets an admin remove the last admin (PATCH/DELETE /users).
    The dashboard closes the one-click route; the server-side refusal is
    a backend change this phase could not make. Suggest it is small and
    early in Phase 32, or its own commit.
  - The narrative job's failure is invisible: root_cause_status stays
    `pending` forever without keys. A `failed` status the panel can show
    is a worker change, not made.
  - Criterion 4 as worded is untestable on error paths (above). Suggested:
    "zero console errors and failed requests on success paths; every 4xx
    is shown to the user; 204s judged by the server's response".
  - The quickstart's compose project name is fixed and its port is 80
    with no override; both are in LIMITS now.
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
