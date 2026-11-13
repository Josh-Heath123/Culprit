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
| Current phase | **37, part 3, continued — one database name; the demo's index; the library's database fault** — `awaiting decision` (**Q35**, blocking items 2–4). Item 1 (Q34) built; item 2 partly built. PR #43 (draft). Brief: `docs/PERFORMANCE_PLAN.md`, end of Phase 37, "Part 3, continued". Step 0: `main`'s push run on `1d20322` and PR #42's last run green, each read by id (the review could not read them). |
| Previous phase | **37, part 3, items 1–3 — merged as `1d20322` (PR #42) and reviewed 2026-11-13** by the architecture session. Items 1–3 are accepted; part 3 continues. Q33 is ruled: (a), static and scoped, with the fault planted in the tree as well as the database. Q34 (one schema database name, derived from the model) was raised by the review and ruled. The review reproduced CI on `1d20322` in its workspace, everything that runs without registry images, all green. Recorded at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-37-index`, to be cut from `origin/main` = `1d20322`. Its first commit is the part 3 review: `git apply ../phase-37-3-review.patch`, then `git commit -F ../phase-37-3-review.txt` (`docs/PERFORMANCE_PLAN.md`, `docs/HANDOFF.md`). Open a draft pull request and mark it ready when the run report is committed. Do not stage `shared/uv.lock`. |
| Blocking questions | **Q35** — the demo's missing index does not make its statement slow for any category it has. |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q35 | **The demo's missing index does not make the list route's statement slow, except for a category with no products.** Measured on the faults stack, PostgreSQL 16, a million seeded rows, the route's statement (`WHERE category = $1 ORDER BY sku LIMIT 50`). At `0002` Postgres plans exactly what `missing_index` diagnoses — it walks `ix_products_sku` for the order and filters `category` row by row — but the seed interleaves categories (`n % 200`), so every seeded category has a match every ~200 skus and the walk stops after ~10,000 entries: **0.8 ms** for `category-007` and for `category-199`, inside the 20 ms budget. Only a category with **no** products walks the whole index: **73 ms**. Part 2's measurement ("about 100 ms a call", the demo budget's `why`, and the sign-off's "(category, sku) brings the statement within budget, which category alone does not") used `category = 'category-7'`, which the seed never writes (it writes `category-007`). For the empty category the brief's three outcomes hold, measured by `TestTheStatementProbesOnTheDemoDatabase` this run: **75.9 ms** at `0002` (fail), **68.7 ms** with a `category`-only index (fail: `not_resolved`), **0.010 ms** with `(category, sku)` (pass: `verified`); EXPLAIN shows the `category`-only index unused for it (78 ms). Under the brief's traffic — the load generator across the seeded categories — the statement is within budget without any index, so the fault is never observed. Options: **(a)** the demo's traffic also asks for categories that exist in the storefront and have no products yet (new categories), enough of it that the window's mean is over the budget, and the featured category of a bare `GET /products` is one of them — the fault becomes "listing an empty category walks the whole sku index"; the numbers above stand; **(b)** a new data migration re-seeds categories in contiguous sku blocks, so a category's rows sit behind every earlier category's — the index becomes `0004`, and whether a `category`-only index then stays unused (the wrong fix's `not_resolved`) is unmeasured; **(c)** something else the architecture session prefers. Not decided here: it is the fault the library plants. Raised 2026-11-13, Phase 37 part 3, continued, item 2. | 2026-11-13 | **Blocking**: items 2 (the `GET /products` budget, the faults stack's database), 3 and 4. |
| — | Q33 and Q34 were ruled on 2026-11-13 (`PERFORMANCE_PLAN.md`, end of Phase 37, "Architecture review of part 3, items 1–3"). Q33: (a), with the Python extractor run with `--no-import` and `want: [db_schema]` for `inventory-service` only; the fault is planted in the tree as well as the database; the library's walks run the extractors. Q34: a component's schema database is the one it connects to by its one `sql` edge (else `<component>-db`); environment names are held to it; extractors are told it; severity uses its inverse. | | |

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
| 37, part 1 | Reading the database safely | **complete** (PR #39 `b3ef508`, close-out PR #40 `ee3e19e`) | **Signed off 2026-11-12** (architecture session): a read-only session refused at the server in CI; the demo's database is seeded; index facts are found both ways. Q27 ruled package isolation, built in the close-out. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 1 close-out | Package isolation; one schema for both manifest readers | **complete** (PR #40 merged, `ee3e19e`) | **Signed off 2026-11-12** (architecture session): every check on the pull request was green, read from GitHub. The audit's two attacks no longer type-check; each boundary package has one non-test file. The CodeQL alert was answered by redesign. Q28 is ruled (strict typing and a differential corpus, in part 2); Q29 is ruled. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 2 | Statements and plans | **complete when `main`'s push run on `1b2496b` is green** (PR #41 merged) | **Signed off 2026-11-13** (architecture session): every check on the pull request was green, read from GitHub. The generic plan comes from a prepared statement under `force_generic_plan` (the brief was wrong). `(category, sku)` brings the statement within budget, which `category` alone does not. Q28's corpus holds 5,684 manifests. Q31 and Q32 are ruled. Decisions are at the end of Phase 37 in `PERFORMANCE_PLAN.md`. |
| 37, part 3 | The database in the walk | items 1–3 **merged** (PR #42, `1d20322`); continued: Q34 built, item 2 partly built, **awaiting decision** (Q35) | **Reviewed 2026-11-13** (architecture session): items 1–3 accepted; Q33 ruled; Q34 raised and ruled. **Brief (2026-11-13):** `docs/PERFORMANCE_PLAN.md` Phase 37, "Part 3, continued" at the end of the section: its work order, criteria and what not to build. Step 0: `main`'s push run on `1d20322` and PR #42's last run green, by id. Branch `phase-37-index` from `origin/main` = `1d20322`; its first commit is the review (`../phase-37-3-review.patch`, message `../phase-37-3-review.txt`). Open a draft pull request and mark it ready when the run report is committed. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
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
Phase:        37, part 3, continued — one database name; the demo's index;
              the library's database fault
Branch:       phase-37-index, from origin/main = 1d20322. 3bd5eb1 the
              review (applied cleanly), 252ae28 Q34, 1327410 item 2 in
              part, ee7d0bf and 0a4b223 fixes, then this report. PR #43.
Run:          2026-11-13, /next.
Status:       AWAITING DECISION (Q35, blocking items 2-4). Item 1 (Q34)
              built and audited; item 2 built in part. CI green on
              ee7d0bf (run 43473708115, every job); the later commits'
              run is on the pull request.

STEP 0
  main's push run 43446256013 on 1d20322: success (deploy skipped).
  PR #42's last run 43442473110 on 5ee22a1: success (publish, deploy
  skipped). Both read by id.

ITEM 1 — Q34, ONE DATABASE NAME (252ae28, ee7d0bf, 0a4b223)
  The rule: extract.Manifest.SchemaDatabase (cli/internal/extract/
  databases.go). The target of a component's one sql edge, else
  <component>-db (two or more edges: <component>-db, nothing joins).
  - Environments: database.name, where given, must equal it, or the
    manifest is refused naming both; DatabaseName takes the manifest and
    keeps no <component>-db of its own. The API's reader refuses the same
    (_check_database_names, Q28).
  - Extractors: the orchestrator sends `database` (Go and Python request
    models, EXTRACTOR_PROTOCOL.md). The Python extractor uses it, and
    falls back to <component>-db only when none is sent. The reference
    extractor's request model forbids unknown fields, so it refused every
    request carrying `database` until it learned the field: an extractor
    must be updated with the orchestrator (EXTRACTOR_PROTOCOL.md, LIMITS).
  - Severity: owners are the rule's inverse, not a suffix trim; shown
    red on the old code.
  - probe.Sources carries the manifest, so the probes' DSN lookup uses it.
  The corpus: its base named shop's database `shop` while shop's one sql
  edge is to `db`, so every case would have been refused; the base now
  names `db` and was re-recorded. The invariant audit then found the
  re-recorded corpus no longer showed the readers type database.name's
  forms alike (the equality refuses all but two forms first). The corpus
  gained `pairs`: one form names the database component, the sql edge,
  calls_to and database.name at once, in every form; 16 are accepted,
  among them yes, no, on, off, inf, 1e999 and dates. Go and Python agree
  on all 5,775 cases.

  RENAMED SUBJECTS (every one)
  - This repository (culprit.yaml: culprit-api's one sql edge is to
    culprit-db): 317 schema subjects on 33 tables, culprit-api-db ->
    culprit-db — agent_allowances, agent_audit_log, agent_nonces,
    agent_pairing_codes, agent_tasks, agents, ai_change_records,
    anomalies, api_keys, architecture_decisions, captures, components,
    configured_facts, connections, contracts, divergences,
    fault_edge_readings, fault_edges, hypotheses, incident_anomalies,
    incident_candidates, incident_change_links, intent_facts,
    invariant_violations, investigation_readings, investigations,
    narrations, observed_service_edges, postmortems, raw_events,
    readings, users, verifications, each with its columns.
    culprit.yaml's two database.name entries follow.
  - cli/testdata/demo: orders-api-db -> orders-db (orders: 6 columns,
    order_lines: 4), billing-api-db -> billing-db (invoices: 4): 17
    subjects. In the check e2e key, the diff e2e expectations, README's
    example and docs/captures/check.svg (regenerated by
    `just readme-captures`; probe.svg changed only its ephemeral port and
    was not committed).
  - cli/testdata/envdiff/{live-ddl-behind-head,clean-environments}:
    orders-api-db -> orders-db.
  - docs/PROBES.md's example: culprit-api-db -> culprit-db.
  - Left as they are: fixtures whose component has no sql edge
    (faults/column-not-migrated, capture tests), literal subjects in unit
    tests and conformance files (no manifest behind them), and
    docs/demos/phase-29.md and phase-30.md, which are transcripts of what
    those phases printed.
  Self-check: green, "No divergences. 1712 fact(s) compared across 630
  subject(s)". It cannot show a disagreement between culprit-api and
  culprit-worker on culprit-db: culprit-worker has no extract root, so it
  contributes no schema facts (phase-auditor).

ITEM 2 — THE DEMO, IN PART (1327410)
  Built: 0003_products_category_sku, (category, sku); setup_db's
  INVENTORY_MIGRATION_TARGET (part 2's statement test now pins 0002, the
  database before 0003); the static, scoped extract: section (Q33 (1))
  with its comment rewritten; an `exists` invariant for GET /products;
  environments faults-inventory (the fault's vantage: stats and plan, no
  db.metadata.read, so verification's capture holds no schema the fix
  changes) and local-inventory (live schema, statements, plans); the load
  generator's products traffic; the extractor's demo-migration test and
  TestTheDemoDatabase at the 0003 head.
  GET /products now answers a request with no query, for the featured
  category: probe.http.latency refuses a URL with a query by design (the
  budget is on the route, never on an input), and the route required
  ?category=, so no budget on it could be judged. A demo change, not a
  product one; the architecture session may prefer another.
  Not built: the GET /products latency budget (its value rests on the
  fault's time; see Q35) and the faults stack's database. The latter is
  written — Postgres 16 with pg_stat_statements, the demo's setup job,
  Culprit's culprit_reader (pg_read_all_stats, SELECT on products) as a
  one-shot, products-only traffic — and saved outside the repository as
  ../phase-37-index-faults-stack.patch, because it needs item 3's harness
  (healthy() recreates every service, which would reseed a million rows
  per case). Brought up by hand: 32 s from cold, seeded, at 0003.

STOPPED AT — Q35 (blocking)
  On that stack, at 0002, the route's statement takes 0.8 ms for any
  seeded category: the plan is the missing-index plan, but the seed
  interleaves categories, so the sku walk stops after ~10,000 entries.
  Only a category with no products is slow (73 ms). Part 2's "about 100
  ms" was measured on category-7, which the seed never writes. Numbers
  and options in §3.

CRITERIA (part 3, continued)
  Q34 — test of the rule (none, one, two edges; name agrees, refused)  PASS
  Q34 — culprit intent on the demo, fresh clone, names
        schema:inventory-db/public.products.category                PASS
  Q34 — three things on one database for the demo
        (TestTheDemoSchemaIsOnOneDatabase, Docker, in CI), red when
        the extractor ignores the name (shown, twice)                PASS
  Q34 — severity finds an owner not named <owner>-db                 PASS
  Q34 — every renamed subject listed                                 PASS (above)
  Q34 — the self-check green, or a divergence escalated              PASS (caveat above)
  Q33 — extract: is --no-import, want [db_schema], inventory-service PASS
  Q33 — the library's walks run it                                   NOT RUN (Q35)
  Q33 — existing expected.json unchanged, results.json listed        NOT RUN (Q35)
  The library's database fault: missing_index complete, verified,
        not_resolved                                                 NOT RUN (Q35)
  The healthy stack: the quickstart at 0003 within both budgets      NOT RUN (Q35:
        the GET /products budget is not declared; the statement at 0003
        is 0.010 ms against 20 ms in TestTheStatementProbesOnTheDemoDatabase)
  A2 — why 25 labels where the brief said 23                         ANSWERED: rerunning
        the close-out auditor's own harness at d37542e gives 25 (1b358a9).
        One, inv_value_huge, differs only past six significant digits —
        the harness's float formatting, labelled so. Which other the
        report left out cannot be recovered; all 25 kept and checked by
        label: budgets_null, comment_only, comp_name_int, empty_doc,
        inv_value_1e3, inv_value_date, inv_value_huge, inv_value_list,
        mp_float_frac, mp_int_tag_str, mp_null, mp_quoted, mp_true,
        probe_enabled_1, probe_enabled_str, probe_timeout_float,
        version_str, version_true, why_float, why_inf, why_int,
        why_octal, why_python_tag, why_timestamp_tag, why_true.
  CI green, fault library <= 15 min or sharded                       PARTLY: green on
        ee7d0bf; the job took 11m42s on 1d20322. The database fault will
        add several 30 s windows and will need sharding (item 3).
  LLM_PROVIDER=none changes nothing                                  unchanged (no
        narration path touched; the fault-library job runs with none).

AUDITS
  phase-auditor (Q34, Q33 (1)): six of seven PASS by execution; the
    seventh was this list. Both readers refused a disagreeing name on its
    own manifests, from a fresh clone.
  invariant-auditor (252ae28..ee7d0bf): CLEAN, 0 violations. Four risks,
    all fixed in 0a4b223: the corpus coverage (pairs), the three-way test
    capturing as the owner (now a grantless reader), DatabaseName
    untrimmed, two stale comments.

LOCAL GATES (Windows)
  go vet ./..., gofmt, just cli-lint, go test ./...: clean.
  Docker: TestIndexesDeclaredAndLive, TestTheDemoDatabase,
  TestTheDemoSchemaIsOnOneDatabase, TestTheStatementProbesOnTheDemoDatabase,
  the dbsession tests: pass.
  api + shared: 1143 passed; scripts/tests: 554; extractors/python: 38;
  just lint, typecheck, lint-imports, check-invariants,
  check-no-llm-imports, check-schema-drift, check-scan-coverage: clean.
  CI caught one thing local runs missed: the subject-construction gate
  (scripts/tests) on a literal subject prefix in a new extractor test;
  fixed in ee7d0bf without touching the gate.
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
