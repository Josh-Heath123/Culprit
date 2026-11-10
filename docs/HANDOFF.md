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
| Current phase | **33, part 3 — The operator's surface** — status `in progress`: implemented; every criterion passes, the CI-only ones in CI. PR #31: CI/CD run 42805541738 green on `17b5b36`, every pull-request check green, no open code-scanning alert (§5). Awaiting the architecture review and Q19. |
| Previous phase | **33, part 2 — The agent meets the control plane: complete**, signed off 2026-11-10 by the architecture session. Merged via PR #28 (`58e7593`), every pull-request check green including code scanning (Q18). Criteria 8–10 verified as CI-run: the `e2e` job runs `just agent-e2e` unconditionally and the test cannot skip. Decisions at the end of Phase 33 in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Paused, 2026-11-05 — Malcolm's decision.** `culprit-vm` is taken offline: it had served an unpatched, pre-Phase-14 API publicly since August. From Phase 32.2, `deploy` runs only when started by hand. Phase 33 builds against a local control plane; "deploy must be green by Phase 33" (2026-09-12) is superseded (`DIAGNOSTIC_PLAN.md`, Phase 33, "Added 2026-11-05"). |
| Branch | `phase-33-operator`, fast-forwarded to `origin/main` = `fdc6f84` (the licence merge) before the work began. Lands through a pull request. Do not stage `shared/uv.lock`. |
| Blocking questions | **None.** Q19 is open and does not block (§3). |

---

## §3. Open questions

Unresolved items only. Numbering continues from the retired list, so a number
is never reused.

| # | Question | Raised | Blocks |
|---|---|---|---|
| Q19 | Accept `api-reader` SELECT on `agent_nonces` (migration `e5b8a2d4c6f1`)? The agents screen shows each agent's last signed request. That moment is already written, as the `seen_at` of the nonce each signed request spends, and the gateway's cleanup now keeps every agent's newest nonce. Reading it needs `api-reader`, which serves the agents listing and already reads `agents`, `agent_allowances`, `agent_tasks` and `agent_audit_log`. Argued in the migration under standing invariant 3's three conditions for a read grant, revoked by its downgrade; no write is widened. It reverses one sentence of `d7a3e5f1b9c2` ("never the codes or the nonces"). The phase-auditor asked for a human ruling rather than the phase naming itself as a precedent in `.claude/rules/database.md`, so that edit was withdrawn. If rejected: a new read-only role for that one listing, or drop "last signed request" from the screen. | 2026-11-10, Phase 33 part 3 | Nothing: part 3 is built on it, and a rejection is a small follow-up. |

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
| 33, part 3 | The operator's surface | in progress — PR #31, CI green; awaiting review | **Brief (2026-11-10):** `DIAGNOSTIC_PLAN.md` Phase 33 — "How Phase 33 is run", then "Part 3" at the end of the section: work order, nine criteria, what not to build. **Preconditions:** the licence pull request has merged, and Malcolm has regenerated the local `infra/.env.prod` and quickstart volume. Carried-in items first (signature before body; plain `http` refused). Screenshots of the new screens at four widths in the run report, for Malcolm. Branch `phase-33-operator`. Lands through a pull request. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 34 | Verification loop and calibration | not started | — |
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
Phase:        33, part 3 — the operator's surface
Branch:       phase-33-operator, fast-forwarded to origin/main = fdc6f84 (the
              licence merge, PR #30). Commits 01f974e..HEAD.
Run:          2026-11-10, /next.
Status:       IMPLEMENTED; CI GREEN on PR #31 (/ci below). Every criterion
              passes, executed — locally, and the CI-only ones in CI. The
              Kubernetes recipe could not run locally (fetching kind was
              refused) and ran for the first time in CI: red twice, then green.

PRECONDITIONS (checked, not assumed)
  Licence PR #30 merged (fdc6f84). infra/.env.prod written 10:37 and the
  quickstart Postgres volume created 10:38 on 2026-11-10, after the part 2
  sign-off: Malcolm's regeneration. Not read: the file's contents.

CARRIED IN
  1 Signature before body (01f974e). The four signed routes that take a body
    declare none; signed_body()/submitted_body() authenticate over the raw
    bytes, then parse them. Test first, red before ("POST /agents/me/audit,
    unsigned: 422 ... JSON decode error"), green after.
  2 Plain http refused (f76c731). https only; http to localhost, 127/8 or ::1,
    or with control_plane.allow_plain_http: true, which `culprit agent` and
    `agent pair` report at every start. Red first (12 cases + the report
    test). CI's agent end-to-end config sets allow_plain_http (a test's, not a
    recipe's). internal/agent uses net/netip: the D8 allowlist caught `net`.
  3 Quickstart under a terminal (ba36bed). `docker compose run -T` on the
    bootstrap step. Reproduced in a separate worktree (own .env.prod,
    culprit-qs-333, port 8333) under `script` in WSL, each from a fresh
    volume: before, the transcript ends at "Password:" and nothing follows for
    60 s; after, it runs to the end, "created admin user 'admin'", sign-in as
    that admin 200. CI now runs the quickstart under `script` too. getpass
    still prints its prompt text as it reads the pipe (LIMITS).

WHAT WAS BUILT
  - Settings -> Agents (089270d): every agent, paired or revoked, its last
    signed request, its reported grants in plain words marked allowed or not;
    a pairing code shown once; an allowance edited with a diff before Save;
    revoke after confirmation. GET /agents gains last_request_at (818cfdd):
    the newest nonce's seen_at; the cleanup keeps each agent's newest nonce;
    migration e5b8a2d4c6f1 gives api-reader SELECT on agent_nonces (Q19).
  - The investigations page, for an admin: "Investigate through an agent":
    agent, environment, symptom, optional vantage; the task's progress; the
    investigation opens when it lands. Without net.tcp.connect and
    net.http.outbound allowed it names the missing grant, says where to give
    it, and starts nothing.
  - The minimum grant set per class (65494ab), in PERMISSIONS: reachability
    {net.tcp.connect, net.http.outbound}; schema {db.metadata.read}; auth and
    audience {config.inspect.values, net.tcp.connect, net.http.outbound};
    configuration {config.read.names}. Found by running every class with all
    seven candidate grants and removing each in turn.
  - deploy/agent/ (bcb3e39): Docker, Compose, Kubernetes, systemd, a README,
    agent.example.yaml. cli/Dockerfile ships /var/lib/culprit owned by 65532.
  - docs/SECURITY.md (a76756f): six threats, 55 test references, held by
    scripts/check_security_doc.py in CI.
  - A link to the source on every page, VITE_SOURCE_URL (c2f38de).
  - README, LIMITS, PERMISSIONS, UPGRADING (e5b73f0, 8d440e5).

CRITERIA (part 3)
  1  401 before the body is parsed, on every agent route    PASS. The test
       finds signed routes from the real app's dependency tree; the auditor
       also curl'd all six against a running stack: 401 for not-JSON and
       wrong-shape bodies, unsigned and forged.
  2  quickstart under a pty: no prompt, admin from .env.prod;
     shown failing first                                     PASS locally
       (above); the auditor reproduced the mechanism independently. In CI:
       the e2e job now runs it under `script` (see /ci).
  3  plain http refused but for loopback / allow_plain_http;
     reported at every start; no recipe sets it              PASS.
  4  every agents-screen action a browser journey in CI      PASS locally,
       18/18 against a quickstart of this branch (culprit-qs-334, port 8334):
       a real agent from the Compose recipe, paired with a code made in the
       browser, appears; the allowance diff shows exactly the two additions
       before Save; revoke, then the agent's own log shows its next claim
       answered 401; a member sees "This page is for admins". Every action is
       taken from the keyboard. In CI: /ci.
  5  dashboard -> investigation end to end with a real agent;
     with no agent holding the grants it explains and starts
     nothing                                                 PASS locally.
       The test counts task requests: none while not allowed, one after.
  6  each class with exactly its documented grants complete;
     each grant removed partial, and named                   PASS. Reads the
       table from PERMISSIONS; mutation-checked (an extra grant, and a missing
       one, each turn it red). Real probes, gate, walk and agent; a fake
       network, HTTP and database holding the fault.
  7  Compose is the one CI runs; Kubernetes Ready in kind;
     systemd verify; no recipe allows plain http            Compose PASS
       locally (deploy/agent/compose.yaml unchanged, plus a CI overlay adding
       one host alias). systemd PASS (systemd-analyze verify, systemd 249,
       WSL). No recipe sets allow_plain_http (test_agent_recipes.py).
       Kubernetes PASS in CI (run 42805541738): "pod culprit-agent-...:
       ready=true restarts=0 runAsUser=65532 readOnlyRootFilesystem=true";
       "kind-agent-78058da0 Ready, non-root, read-only root, last signed
       request 2026-11-10T11:19:31Z" — so the key Secret, 0600 under fsGroup,
       was readable by the agent. systemd-analyze verify PASS in CI too.
  8  every "cannot" names a test that exists                  PASS (55).
  9  tokens only; four widths; keyboard; screenshots here     PASS locally:
       check_frontend_tokens over 69 files; atEveryWidth at 375/768/1280/1920
       with an overflow check, Tab reach and a focus ring; the journeys
       operated by keyboard. Screenshots: the e2e-screenshots artifact of the
       /ci run below: settings-agents-*, agents-pairing-code-*,
       agents-allowance-*, investigate-unavailable-*, investigations-*. Not
       committed (6.3 MB).
  10 LLM_PROVIDER=none changes nothing                        PASS.

GATES (local, Windows, Docker up)
  lint, typecheck, lint-imports, check-schema-drift, check-no-llm-imports,
  check-invariants, check-scan-coverage, check-frontend-tokens,
  check-security-doc, cli-lint                                PASS
  just test   api+scripts+shared 1169 / 6 skipped, worker 65, mcp 21,
              extractors 31 + 22, go test ./...                PASS
  frontend npm test (19), tsc -b                               PASS
  check-migration-round-trip                                   PASS
  culprit check / LLM_PROVIDER=none                            exit 0 / 0
  just e2e (18/18) and just agent-e2e, against culprit-qs-334  PASS
  just agent-recipes                                           NOT RUN locally
                                                               (kind); CI PASS

AUDITS
  invariant-auditor: CLEAN, no violation. Risks taken up: the migration now
    says it reverses d7a3e5f1b9c2, and counts itself correctly; one nonce per
    agent kept for good is in LIMITS; a failure screenshot can no longer hold
    a live pairing code. Left as a risk: a partial diagnosis now repeats the
    refusing probe's reason, already in the hypothesis, so nothing new is
    exposed.
  phase-auditor: every local criterion PASS. Fixed: the pairing-code
    screenshot (now taken after the code is spent); SECURITY.md's one blanket
    claim split into three tested ones; keyboard operation; the schema class
    explained. Raised to you: Q19, and the rule-file edit withdrawn.

DECISIONS TAKEN HERE (for review)
  - Kubernetes is a Deployment of one replica, Recreate, not field 4's
    DaemonSet: one key is one identity and one audit chain.
  - The key Secret is defaultMode 0600; under fsGroup the kubelet makes it
    0640 root:65532 (LIMITS), the closest Kubernetes allows for a non-root
    reader. Shown readable in CI: the pod made signed requests.
  - The dashboard gates on the reachability set only, for any symptom; a walk
    needing more starts, and ends partial naming the grant (LIMITS).
  - Partial-diagnosis wording: "could not be established" now carries the
    probe's reason, so a missing net.http.outbound is named (65494ab). What
    the walk tests, and in what order, is unchanged.
  - The agent exits when its control plane is unreachable; the recipes'
    restart policies bring it back (LIMITS). No retry loop was added.
  - The Compose journey's agent joins the quickstart's own network, where the
    demo services are; it reaches the API only through the published
    address. Part 2's separate-network scenario still runs in agent-e2e.
  - LIMITS corrected: re-pairing to report a new grant means a new agent id
    and key; the control plane refuses a second pairing of either.

/CI — PR #31
  commit   17b5b36aada1c78064d8c913a431cf79f8ffde0f (merge result: origin/main
           fdc6f84 is an ancestor; `git merge origin/main` changed nothing)
  run      42805541738  CI/CD, pull_request, success; CodeQL 42805534032 success
  jobs     lint, typecheck, test, cli, migration-round-trip, self-check,
           kind-capture, fault-library, e2e, build x5: success; publish and
           deploy skipped
  checks   gh pr checks 31: 20 pass, 2 skipping, 0 fail (CodeQL included)
  alerts   none open (pr=31, refs/pull/31/merge, refs/pull/31/head)
  shots    artifact e2e-screenshots (id 13757823643) of run 42805541738
  Earlier runs on this PR, red in the new recipe step only:
    42802523521 (69f192f) rollout timeout, no diagnostics -> 8323e54 adds them;
    42804120023 (8323e54) ImagePullBackOff: `kind load docker-image` left the
    image off the node -> 17b5b36 loads it through an archive, checks it with
    crictl, and sets imagePullPolicy: Never in CI's patch.

LEFT OPEN
  - Q19.
  - A local throwaway stack, culprit-qs-334 (port 8334), and its worktree in
    the session scratchpad: `docker compose -p culprit-qs-334 ... down -v`.
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
