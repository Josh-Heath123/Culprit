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
| Current phase | **32, part 2 — The investigation in the control plane** — status `not started`. Brief in §4 and at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. |
| Previous phase | **32, part 1 — The isolation walk: complete**, signed off 2026-11-04 by the architecture session. Merged via PR #22 (`972f288`); CI green on every job on the merge result (run 41815764073), the `fault-library` job 6/6 on Linux. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Every merge to `main` runs `deploy` (PR #19 `a3f110a`, PR #20 `4f69ab3`), and it is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-32-control-plane` (renamed from `handoff-32-1-complete`), cut from `origin/main` = `972f288`; its first commits are part 1's record-keeping and its sign-off. Do not stage `shared/uv.lock`. |
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
| 31.2 | Present what works | **complete** | **Signed off 2026-11-04** (architecture session): PR #21 green on every job; the review's five corrections and the lockfile change verified on disk in `a18c73e`, with the self-check's numbers evidenced in §5. **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. **Go-ahead 2026-11-04:** the branch `phase-31.2-present-what-works` exists, cut from `origin/main` = `4f69ab3`. Read Phase 31.2 in the plan including "Carried in from Phase 31.1". **Review 2026-11-04 (before CI):** justfile fix ratified with one change (types generated from the lockfile, as CI does); criterion 4 refined; five README and LIMITS corrections to make on this branch before merge — `DIAGNOSTIC_PLAN.md`, end of Phase 31.2. The last-admin guard is Phase 32's third item. |
| 32, part 1 | The isolation walk | **complete** | **Signed off 2026-11-04** (architecture session): PR #22 (`972f288`), CI green on the merge result with the fault library 6/6 on Linux (run 41815764073). Criteria 1 and 3 refined; decisions at the end of Phase 32 in `DIAGNOSTIC_PLAN.md`. **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — all 17 fields, read with "How Phase 32 is run" at the end of the section, which wins where they differ. This run is **part 1 only: the walk, in the binary** — no migration, no API, no frontend, no worker change; those are part 2. Order: the two carried-in items first (CONFIGURED values rendered as shapes; the generated catalogue mirror), then the shared Investigation model and its conformance fixture, then `internal/isolate` and `culprit diagnose`, then the fault library and its CI job. Branch `phase-32-isolation-walk`. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
| 32, part 2 | The investigation in the control plane | not started | **Brief (2026-11-04):** `DIAGNOSTIC_PLAN.md` Phase 32 — "How Phase 32 is run", then "Part 2 — the investigation in the control plane" at the end of the section, which holds the work order, the criteria and what not to build. Branch `phase-32-control-plane`. Order: the carried-in items first (the token grant, the symptom's attestation, untested versus unexplored branches; then the last admin), then storage, the API, the view, the correlation engine's removal, and the quickstart, README and LIMITS last. Replace §5 with this run's report. Do not stage `shared/uv.lock`. |
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
Phase:        32, part 1 — The isolation walk (in the binary)
Branch:       phase-32-isolation-walk, cut from origin/main = 87c1cad; first
              commit 2054b22 (31.2 sign-off + this brief). origin/main has
              not moved, so the working tree is the merge result.
Run:          2026-11-04, /next. Part 2 NOT started.
Status:       COMPLETE, awaiting architecture sign-off. Every criterion met,
              field 15 included; both audits run; CI green on the merge
              result.
Committed:    facd700 (by the human), pushed, merged as PR #22 = 972f288.
CI:           run 41815764073 (pull_request, i.e. GitHub's merge ref),
              head facd700, conclusion success. Every job success: lint,
              typecheck, cli, test, migration-round-trip, self-check,
              kind-capture, fault-library, build+Trivy for api, worker,
              frontend, mcp_server, cli. deploy skipped (PR). The
              fault-library job's log shows all six faults PASS on Linux
              (auth-audience, network-partition, contract, config,
              error-rate, latency; 61.6s). facd700 and 972f288 have
              identical trees. The main push run 41817094537 was in
              progress when this was written; its deploy is expected red
              (Q16, outside the phase gate).

WHAT WAS BUILT (in the brief's order)
  1. Carried in: evidence never renders a CONFIGURED value.
     model.DisplayValue renders a CONFIGURED fact as its ValueShape, never
     its value; conflictEvidence — the only place reading evidence
     rendered a fact's value — uses it. TestEvidenceNeverRendersAConfigured
     Value: granted value absent from text and JSON, pass and fail;
     mutation-tested red.
  2. Carried in: the catalogue mirror is generated. `just probe-catalogue`
     writes api/app/readings/catalogue.json from `culprit probe --list
     --format json`; TestTheAPICatalogueIsGeneratedFromTheBinary compares
     the whole document byte for byte. Mutation-tested (cost, and a
     discriminates entry). Generating it FOUND A REAL DRIFT: the binary
     printed token_shape's capabilities as null, which the Python
     ProbeManifest rejects — the hand-kept `[]` had hidden it. Fixed at
     the source.
  3. The model: Investigation, Hypothesis, FaultEdge, InvestigationReading,
     ConfidenceRubric in Go (cli/internal/model/investigation.go) and
     Python (shared/culprit_model/investigations.py), held together by
     shared/tests/investigation_conformance.json (2 accepted, 11 rejected,
     each one mutation from valid). A FaultEdge with no establishing
     reading cannot be constructed, decoded or validated; every cited id
     must be a reading the investigation took; verified=true is rejected
     until Phase 34. Readings are held as {id, reading} so Reading itself
     is unchanged. Hypothesis kinds are model.HypothesisKinds /
     readings.HYPOTHESIS_KINDS; a manifest discriminating an unknown kind
     fails validation in both languages.
  4. cli/internal/isolate: hypothesis space from the model's request-path
     tree; probe selection by `discriminates` alone, cheapest first;
     bisection down single-child chains; fan-out by children; boundary
     hypotheses (connection, TLS, audience, contract, config, database)
     at the localised component; the edge tested first when the agent
     sits at the parent; budgets; tree assembly; the §2.9 rubric computed
     from readings. Links no network package and not internal/probe
     (go list -deps; TestTheNetworkBoundaryIsAnAllowlist covers it).
     Probe manifests gained `discriminates`.
  5. `culprit diagnose <symptom>`: a subject URI, "METHOD URL" or a
     component name; --env, --from (vantage), --reference, text|json.
     Every probe still runs through probe.Runner and its ledger. Exit 0
     complete, 1 partial, 2 could not run.
     culprit.yaml gains `isolation:` (field 10) and — NOT IN THE PLAN, see
     below — environments.*.endpoints, components.*.tokens, endpoint
     health_path.
  6. The fault library: demo-services gain an audience check
     (shared/demo_auth.py, stdlib HS256), a parameter-free GET /stock
     route, a required PAYMENTS_PROVIDER_KEY and /ready routes that go
     through the fault middleware; demo-services/faults/ is a three-
     service stack; cli/cmd/culprit/faultlib_test.go injects each fault,
     confirms POST /orders really fails (201 healthy, 5xx under the fault;
     latency stays 201), runs the linux binary inside the vantage
     container, and compares root, completeness, every edge, the rubric —
     and asserts no token or secret appears in JSON or text.
     cli/testdata/faultlib/expected.json; `just fault-library`; CI job
     `fault-library`.

DEFECTS THE FAULT LIBRARY FOUND IN THE WALK (and the fixes)
  1. Back-edges. The demo declares inventory->order and payments->order
     on the request path; the walk followed them, so a pass at inventory
     "ruled out" the whole system. The walk now uses the request-path tree
     built breadth first from the entry. Locked by a unit test.
  2. From inside order-service a failing request to inventory crossed the
     edge, and the walk blamed inventory. When the agent sits at the
     parent, the edge is tested before descending (Placement.Vantage).
  3. A root reached only by elimination was "complete". Under added
     latency every probe passes and the entry was blamed. Now partial,
     saying what it might be missing.
  4. probe.net.dns_resolve discriminated connection_unreachable; a name
     that resolves proves nothing about a connection. Removed.
  5. Contract hypotheses on templated routes are inconclusive — the probe
     cannot tell a missing route from a missing item. A real limit
     (LIMITS); the demo's contract route takes its parameter in the query.

ACCEPTANCE CRITERIA (field 14, and field 15)
  1. Auth-audience mismatch: root is the audience config, not the
     500 at the edge                                               PASS
     Fault library, real containers: root
     auth:order-service->inventory-service/audience, complete, reproduced
     and discriminated (6 alternatives ruled out by readings). POST /orders
     answered 5xx under the fault, 201 healthy. phase-auditor reproduced
     it independently.
  2. The tree distinguishes symptom, propagation and root, and every
     edge cites readings                                           PASS by
     the validator's rule; QUESTION for review. All three relations appear
     (the config fault: symptom_of, propagates_to, caused_by). But a
     symptom on a write endpoint cannot be replayed read-only, so the
     symptom_of edge cites the reading that establishes the cause (the
     token reading, the tcp reading) — documented in LIMITS, flagged by
     the phase-auditor as "a borrowed citation".
  3. O(log n) on a six-hop chain, counted                            PASS
     Fault at every position on 7 components: request probes <= 3
     (= ceil(log2 7)); 64 components: <= 6 request probes and <= 12 probe
     executions in all. Mutation to a linear walk turned it red. The
     auditor notes constants dominate at six hops: 7 total executions for
     a fault at c3 (4 request + 3 boundary).
  4. LLM_PROVIDER=none gives a complete, correct tree               PASS
     True by construction — nothing in the binary reads it; the real
     command against a local server, with it set, gives a complete tree.
  F15. Fault library in CI on every push                        PASS
     local 6/6, and 6/6 in CI run 41815764073 (job fault-library).
  Scope: no migration, API, frontend or worker change — PASS (only
  api/app/readings/catalogue.json, which carried item 2 regenerates).

AUDITS
  invariant-auditor   CLEAN. Its risks, and what was done:
    - symptom URL could carry a credential (query/userinfo) — FIXED,
      description keeps scheme/host/port/path only;
    - a typed subject was stored as typed — FIXED, rebuilt canonical;
    - no end-to-end proof the token stays out — FIXED, the fault library
      asserts it every case, both formats;
    - the token is read with NO capability grant — OPEN, for review
      (docs/PERMISSIONS.md says so);
    - Go has no lint against hand-written subjects — standing, as before;
    - report.renderValue / render.describeValue are other value
      renderers (outside reading evidence) — noted.
  phase-auditor       criteria as above. Its fixes made: fault library now
    proves each fault real and compares edges; total-probe bound added;
    isolation: unit tests; a wrong LIMITS sentence corrected.

GATES (working tree = merge result), after the last edit
  lint, typecheck, lint-imports, check-schema-drift, check-no-llm-imports,
  check-scan-coverage, check-invariants, coupled files, cli-lint   PASS
  go test ./... (-count=1)                                          PASS
  just test: api 920 / 4 skipped, worker 101, mcp 21, extractors py 31
                                                                    PASS
  just fault-library                                       PASS 6/6
  self-check (1023 facts, no divergences), LLM_PROVIDER=none       PASS
  check-migration-round-trip                                        PASS
    (earlier in the run; no migration in this phase)
  CI on the merge result                            PASS (41815764073)

DELIBERATELY NOT BUILT (part 1 scope, field 17)
  No migration, no API, no frontend, no worker change — part 2. No
  remediation application (remediation is a string), no verification
  loop (verified always false), no production agent, no postmortem prior,
  no upload from the binary, no trace-id or error-signature symptoms.
  auth_rejected hypotheses are not generated (no protected URL to present
  a token to); --reference exists but no fault exercises it.

FOR THE ARCHITECTURE SESSION
  - Plan deviation: culprit.yaml gained environments.*.endpoints,
    components.*.tokens and endpoint.health_path; field 10 names only
    `isolation:`. The walk cannot place a probe without them, and
    endpoints sit beside components: because the process adapter may
    name only one component (Phase 30's rule, not weakened).
  - The token read has no grant. Should naming a token variable require
    a capability (config.read.values on that key, or a new read grant)?
  - Criterion 2's citation: the symptom_of edge borrows the cause's
    reading when the symptom is a write. Either a symptom-source marker,
    or reword §2.8/criterion 2 (the auditor's two proposals).
  - `complete: true` while untested branches remain `open` (e.g. the
    payments branch in the partition run) — complete means "nothing the
    walk needed went unexplored", not "every hypothesis tested". Confirm.
  - Partition from inside the caller is honestly NOT discriminated
    (refused == down from that vantage); expected.json says so.
  - Proposed rewordings (auditor): criterion 1 "…a complete investigation
    whose root is auth:<caller>-><callee>/audience, and neither the caller
    component nor the symptom"; criterion 3 "…request probes <= ceil(log2
    n) at every position on 7 and 64 components, total executions on 64
    <= 12".
  - The quickstart compose sets a synthetic PAYMENTS_PROVIDER_KEY,
    because payments now requires it.
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
