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
| Current phase | **31.1 — Close the probe loop** — status `in progress`, **awaiting the human's commit and then `/ci`**. Every field-14 criterion executed against the running demo stack and passed (criterion 7's CI half excepted); both audits clean; every local gate green, Docker-backed suites included (§5). Not `complete`: CI on the merge result has not run, because CI needs a commit and the human commits. Brief in §4. |
| Previous phase | **31 — Probes: complete**, signed off 2026-11-03 by the architecture session. Merged via PR #19 (`a3f110a`). CI green on every job on the merge result, after two ambient dependency fixes (`335aa3b`, `96ac919`; §5). Criteria 3 and 4 met; 1 and 2 carried into 31.1 by the review in `DIAGNOSTIC_PLAN.md`. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. Merging PR #19 pushed `a3f110a` to `main`, so `deploy` runs there, and is expected to fail as before until Q16 is resolved. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-31.1-probe-loop`, cut from `origin/main` = `a3f110a`; its first commit is the Phase 31 sign-off. Do not stage `shared/uv.lock`. |
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
| 31.1 | Close the probe loop | **in progress — criteria met locally, CI not run** | **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.1, all 17 fields. Phase 31 is merged; the branch `phase-31.1-probe-loop` is cut from `origin/main` = `a3f110a`, with the sign-off as its first commit. Order within the phase: the two gate repairs first — the boundary allowlist (it must exist before anything else lands under `cli/internal/`) and the emptied `.trivyignore` — then expectations, then data sources, then the demo-stack criteria. Replace the whole of §5 with this run's report. Do not stage `shared/uv.lock`. |
| 31.2 | Present what works | not started | **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. |
| 32 | Fault isolation and the Investigation | not started | Read `DIAGNOSTIC_PLAN.md` Phase 32, including "Added 2026-11-03". The full brief is written when 31.2 is complete. |
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
Phase:        31.1 — Close the probe loop
Branch:       phase-31.1-probe-loop, cut from origin/main = a3f110a.
              origin/main has not moved (fetched 2026-11-03), so the
              working tree IS the merge result.
Run:          2026-11-03, second /next of the day (resumed after the
              disk-full stop). Phase 31.2 NOT started.
Status:       IN PROGRESS — every acceptance criterion executed and PASS
              locally against the running demo stack; both audits clean;
              every local gate green. CI on the merge result NOT RUN:
              it needs a commit, and the human commits.
Committed:    NO, by protocol — staged, message written; the human commits.

WHAT THIS RUN DID (the first run's build is described in git history:
`git log -p docs/HANDOFF.md`; it is unchanged except as listed here)
  The disk-full blocker had cleared (23 GB free, Docker 29.6.2 up). Stood
  the quickstart up with infra/docker-compose.probe-demo.yml layered on
  and executed criteria 1-5 against it, then the Docker-backed suites,
  then both audits.

ACCEPTANCE CRITERIA (field 14) — executed, by this session and again,
independently, by phase-auditor
  1. Phase 31 criterion 1 against the running demo stack          PASS
     `culprit probe connection:order-service->inventory-service`, the
     linux binary run inside order-service, with host/port/url inputs:
     reachability PASS (200); TLS inconclusive, "first record does not
     look like a TLS handshake" — true, the demo serves plain HTTP; route
     conformance inconclusive, "no INTENT fact declares
     http:inventory-service/GET /health" — true, demo-services/culprit.yaml
     has no extract: by design; impedance refused (`local` does not grant
     telemetry.metrics.read), and with the grant inconclusive. The worker
     does produce it: `readings` holds probe.edge.impedance rows for this
     connection from agent culprit-worker (22 pass / 2 fail at first
     look, 224 by the audit), latest within the minute.
  2. Phase 31 criterion 2 as reworded (binary inside A)           PASS
     Partition: an iptables REJECT (tcp-reset) rule in order-service's own
     network namespace, from an alpine sidecar sharing it; neither
     container stopped. Inside A, http.reachable and net.tcp_connect for
     B pass -> FAIL ("connection refused"); DNS from A stays pass; from
     the host, both services' health probes stay PASS; rule removed,
     everything PASS again. order-service -> payments-service unaffected.
  3. route_conformance pass with expected_source / fail on a
     disagreeing declaration, against the served api              PASS
     GET /model/components against the api (127.0.0.1:18000): pass on
     401, expected_source = introspection, culprit-extract-python@0.1.0,
     api/app.main:app, $.paths./model/components.get, rank 90. With
     router.py:98 temporarily declaring /model/component-list: FAIL,
     "is declared but the running service answers 404", citing the
     changed declaration; the served-but-undeclared route then reads
     inconclusive. router.py reverted, diff empty.
  4. db.schema_conformance pass / fail naming the dropped column  PASS
     public.contracts (empty by design): pass, then after
     `alter table contracts drop column created_at` FAIL, "missing
     column(s) the code maps: created_at"; column restored exactly.
     Connected as a throwaway LOGIN role with NO grants (pg_catalog is
     enough), dropped afterwards — see "Environment" below for why not
     api-reader.
  5. no fixture credential in any reading, text or JSON           PASS
     Live: the DSN password 0 times in text and JSON, pass and fail.
     Audit: four bad DSNs and a fixture JWT, 0 matches.
  6. a new internal/ package linking net/http turns the boundary
     test red with no edit                                        PASS
     (re-run by the audit: zzaudit named for net, crypto/tls, net/http)
  7. .trivyignore holds no entries                                PASS
     every image's scan green in CI                               NOT RUN

FIELD 13 — "at least one run of each newly wired probe against the real
demo stack": db.connect / db.schema_conformance PASS (above, and the
audit's bad-DSN runs). config.present was in the audit's criterion-1
run inside order-service, but its verdict was not reported back, so it
counts as NOT RUN here. dep.version was NOT RUN against the stack (the
demo declares no `packages:` command). Both pass their fixture suites.
Field 13 is therefore partly met.

DEFECTS FOUND AND FIXED IN THIS RUN
  1. The overlay's partition did not work. Disconnecting order-service
     from `default` (the first run's untested assumption) also kills
     Docker Desktop's host port forward to it — host health went
     inconclusive/EOF while the container still answered on its second
     network. gw_priority on that network did not help either. Replaced
     with the in-namespace REJECT rule; the order-edge network removed;
     why both alternatives fail is in the overlay header and LIMITS.
  2. probe.edge.impedance's CLI reason was "this agent cannot read
     telemetry" — true but not what criterion 1 asks a reason to say
     (that the worker produces it). Now says so. LIMITS claimed it
     already did; corrected, and it now also says no endpoint serves
     stored readings yet (POST /readings only).
  3. Doc corrections from phase-auditor: PROBES.md (http.reachable also
     fails on a refused connection; 4xx/timeout inconclusive), LIMITS'
     network-boundary section still described the pre-allowlist test,
     the overlay header now says the REJECT rule cuts both directions.
  4. docs/UPGRADING.md said a quickstart never needs upgrading steps.
     False — see Environment; LIMITS now documents it.

ENVIRONMENT — what this machine needed, none of it product code
  - infra/.env.prod is from 2026-09-09, before Phase 28: it lacks
    FACT_/CAPTURE_/PROBE_WRITER_* and CULPRIT_PROJECT_TOKEN, so the
    bootstrap migration aborted and api/worker crash-looped. Reading that
    file was DENIED to this session, so it was not opened or edited: the
    missing seven were generated into a scratchpad env file and appended
    to the services through a throwaway compose overlay. The human should
    add those keys to the real file (names in .env.prod.example). New
    LIMITS paragraph: re-running `just quickstart` does not fix this, and
    `--force` regeneration breaks the existing volume's passwords.
  - Port 80 on this host is held by an Apache inside WSL; every
    localhost/api request got its 404. The overlay now publishes the api
    itself on 127.0.0.1:18000, which is also the better measurement (the
    service that declares the routes, not a proxy). LIMITS: route
    conformance cannot tell which server answered.

AUDITS
  invariant-auditor   CLEAN on all seven invariants, whole diff. Risks it
                      raised, for a human (not fixed — out of scope or
                      not yet reachable):
                      - expect.go's conflictEvidence writes a competing
                        fact's raw canonical value. Unreachable for a
                        config value today (no CONFIGURED-measured probe
                        sets expected_source); a future one would leak a
                        granted value. Render a shape for CONFIGURED.
                      - test_the_catalogue_mirrors_the_go_source checks
                        only id/effect/timeout; this phase's version,
                        predicate and input changes match only because
                        they were diffed by hand.
                      - the partition is a privileged manual command; it
                        must stay a doc comment, never a recipe or probe.
  phase-auditor       6/7 PASS, criterion 7's CI half NOT RUN. Its doc
                      findings fixed (above).

GATES (working tree = merge result)
  lint, typecheck, lint-imports, check-schema-drift       PASS
  check-no-llm-imports, check-scan-coverage,
  check-invariants, coupled files --base origin/main       PASS
  cli-lint, go test ./... (re-run after the last edit)     PASS
  just test: api 889 passed / 4 skipped (the standing
    "sanctioned implementation" parametrize skips),
    worker 101, mcp_server 21, extractors py 31           PASS
  extractors node 22                                       PASS
  check-migration-round-trip                               PASS
  cli-test-docker (TestEnvironmentDiffAgainstRealContainers) PASS
  cli-test-kind                                            NOT RUN (no
                                                           `kind` on this
                                                           host; CI job)
  culprit check --fail-on=breaks_request_path              PASS 0
                                                           divergences,
                                                           1023 facts
  LLM_PROVIDER=none culprit check                          PASS
  CI on the merge result                                   NOT RUN

DELIBERATELY NOT BUILT (field 17)
  No probe selection, no fault trees, no new probe (still 13), no new
  capability, no agent transport, no change to how impedance is
  produced — only the CLI's inconclusive wording about it.

PLAN CORRECTIONS — for the architecture session
  - Criterion 2 (reworded) says the block "flips exactly A's reachability
    probe for B". A REJECT rule in A's namespace also eats A's replies,
    so B's probe of A goes inconclusive too; and http.reachable and
    net.tcp_connect both flip, being the same reachability at two layers.
    Suggested wording: "flips A's reachability probes for B to fail while
    A's and B's own health probes, taken from the host, stay pass".
  - Criterion 4 says "a column the migrations declare". The expectation
    is taken from ORM introspection (rank 90), which outranks the Alembic
    chain; the two agreed, so no conflict. Correct per §2.4, but the
    criterion names the lower-ranked source.
  - Carried from the first run, unchanged: field 4's predicate mismatch
    (decided: manifests at v2), criteria 3/4 run against the quickstart
    api, not the demo services (decided), the dsn input removed,
    dep.version inconclusive on ranges, --capture changes no built-in
    reading yet.

TO FINISH THIS PHASE
  1. The human commits (command below the report in the session).
  2. /ci: green on every job, Trivy on every image with the empty
     .trivyignore. If an image goes red, fix the image — never restore a
     line.
  3. Merge, then the architecture session signs off.
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
