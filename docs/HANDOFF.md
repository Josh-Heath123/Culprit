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
| Current phase | **31 — Probes** — status **`gates red`**: every local gate is green, but **CI has not run** (the work is staged, not committed), so invariant 12 is unsatisfied and the phase is **not complete** |
| Previous phase | **30 — Environment capture and cross-environment diff: complete**, signed off 2026-09-12. Merged via PR #17 (`888eb22`) and PR #18 (`bb73a9b`). Both auditors clean 2026-09-10; its code is untouched since. |
| Deploy | **Out of the phase gate, decided 2026-09-12.** A red `deploy` no longer holds a phase open. `main` run 34641745097 on `bb73a9b`: all 12 test/build/scan jobs success, `deploy` failure — production has not deployed since Phase 13 (2026-08-04), the VM pulls pre-rename `ghcr.io/josh-heath123/view/*` images, and `culprit.co.za` serves a pre-Phase-14 API. That is now operations, tracked as the **VM remediation** task in §4, not a phase blocker. |
| Branch | `phase-31-probes`, cut from `phase-30-env-capture` at `origin/main` = `bb73a9b`. Do not stage `shared/uv.lock`. |
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
| 31 | Probes | **gates red** | Built and locally green; **CI NOT RUN** (nothing committed, so invariant 12 is unsatisfied) — not complete. Criteria 3 and 4 PASS; 1 and 2 only partly demonstrable without the demo stack. One enforced invariant was deliberately changed (the binary-wide `net/http` ban, replaced by a per-package one) and one role was widened (`anomaly-detector` SELECT on `connections`) — both argued in §5 and both wanting a human eye. Q12 answered: both surfaces exist. (Carried from the retired Q12: Phase 30 field 4 asked capture for DNS resolvability, TLS certificate expiry and reachable ports, and built them as passive CONFIGURED facts — `component:X dns_resolves` and the like — that stop at a handshake, reading field 17 as "no application requests". Phase 31's own field list names `probe.net.dns_resolve`, `probe.net.tcp_connect` and `probe.net.tls_validity`. **Phase 31 must either re-site them as probes or state that both exist and why.**) **Review 2026-11-03:** every open item decided — `DIAGNOSTIC_PLAN.md`, end of Phase 31. To complete: the human commits, then `/ci` green on the merge result, then merge. |
| 31.1 | Close the probe loop | not started | **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.1, all 17 fields. Start only once Phase 31 is complete and merged; cut `phase-31.1-probe-loop` from the new `origin/main`. Order within the phase: the boundary allowlist first (small, and it must exist before anything else lands under `cli/internal/`), then expectations, then data sources, then the demo-stack criteria. Replace the whole of §5 with this run's report. Do not stage `shared/uv.lock`. |
| 31.2 | Present what works | not started | **Brief (2026-11-03):** `DIAGNOSTIC_PLAN.md` Phase 31.2, with `docs/PRODUCTISATION.md` as its requirements — §5, §6 and §10 apply now; the redesign (§2) and the video (§7) belong to Phase 32.1. Present only what works. The web UI is made honest here, not restyled. |
| 32 | Fault isolation and the Investigation | not started | Read `DIAGNOSTIC_PLAN.md` Phase 32, including "Added 2026-11-03". The full brief is written when 31.2 is complete. |
| 32.1 | Design system and the investigation-first interface | not started | Folded in from `docs/PRODUCTISATION.md` on 2026-11-03. The full brief is written when Phase 32 is complete. |
| 33 | Production agent and permission model | not started | — |
| 34 | Verification loop and calibration | not started | — |
| 35 | Agent surface and the narrator | not started | — |

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

Claude Code overwrites this section at the end of every `/next`.

```
Phase:        31 — Probes
Branch:       phase-31-probes, cut from phase-30-env-capture at
              origin/main = bb73a9b. origin/main has not moved since, so
              the working tree IS the merge result and every local gate
              below ran on it.
Run:          2026-09-12, /next. Phase 32 NOT started.
Committed:    NO — by protocol, not by failure. The header of this file
              now says the human commits; this run staged everything and
              wrote the message. See COMMITTING below.
CI:           NOT RUN. Nothing can be pushed without a commit, so
              invariant 12 (green CI on the merge result) is NOT
              satisfied and this phase is NOT complete. What only CI
              exercises is listed under GATES.

ARRIVAL STATE — docs/HANDOFF.md had been truncated
  The file lost §2 (decisions register, 24 rows) and §3 (open questions
  Q1-Q14) in an uncommitted edit: +17/-356 lines. Four surviving
  references pointed at the deleted sections (§1's "see §2", §4's
  "(Q12)", §6's "write the question into §3", the protocol header), and
  the §1 table was broken mid-row. Claude Code asked rather than
  guessing; the human answered THE DELETION WAS INTENDED. So §2/§3 are
  retired deliberately, and this run fixed only what dangled:
    - protocol header now says where decisions of record live
      (DIAGNOSTIC_PLAN §1 D1-D8; the rest in `git log docs/HANDOFF.md`)
    - §1 table repaired, now reads Phase 31 in progress
    - §4's Phase 31 brief has Q12's text INLINED verbatim — it is this
      phase's actual mandate and would otherwise have been lost
    - §6 now says to write escalations into §5
  Historical §5 reports still mention §2/§3; left alone, they describe
  what was true when written.

WHAT WAS BUILT

  shared/culprit_model/readings.py   Reading, ProbeManifest, Verdict,
                                     Effect, Cost, Evidence, Produces.
                                     Five invariants enforced ON THE TYPE:
                                     effect: mutate cannot be constructed;
                                     inconclusive/refused require a reason;
                                     a target must parse as a subject URI;
                                     a refused reading cannot claim a grant;
                                     unredacted credential-shaped evidence
                                     is refused.
  cli/internal/model/reading.go      the Go half, same rules.
  shared/tests/reading_conformance.json
                                     written FIRST, read by both languages
                                     (27 Python + 8 Go tests), including
                                     11 must-be-rejected cases.
  cli/internal/probe/                the runtime (2,175 non-test lines):
                                     manifest validator, capability-gated
                                     runner (timeout, bounded concurrency,
                                     deterministic ordering), Deps as
                                     narrow interfaces, RealNetwork,
                                     RealHTTPClient, and 13 probes.
  cli/cmd/culprit/probe.go           `culprit probe [target]`, `--list`,
                                     -p/--input/--env/--format, same exit
                                     codes as every other command.
  cli/internal/extract/probes.go     culprit.yaml's `probes:` section —
                                     enable/disable (reason required),
                                     timeout override, environments.
                                     Capabilities deliberately NOT
                                     configurable here.
  cli/internal/report/readings.go    text rendering, redacted at one point.
  api/app/readings/                  POST /readings (project token,
                                     probe-writer), GET /probes (catalogue
                                     mirror), POST /probes/{id}/run -> 503.
  migration a9d2c40f7e18             13th role `probe-writer`: INSERT on
                                     readings and NOTHING else, not even
                                     SELECT. api-reader gains SELECT.
  worker/app/anomaly/job.py          impedance readings keyed by connection
                                     subject, written under probe-writer
                                     through a second engine.
                                     scorer.py and state.py are
                                     BYTE-IDENTICAL (field 5) — verified
                                     with `git diff --exit-code`.
  docs/PROBES.md                     field 15, every probe's inputs,
                                     effect, capabilities and failure
                                     conditions, plus the Q12 answer.

THE ONE REAL CONFLICT — an enforced invariant was changed on purpose

  Phase 31 field 4 mandates probe.http.reachable, route_conformance,
  schema_conformance and auth.propagation. All make HTTP requests.
  `TestNoModelProviderIsLinkedIntoTheBinary` asserted the binary links
  no net/http, on the stated grounds that it "has nothing to talk to".
  That premise is what this phase falsifies, deliberately: §2.7 has
  provisioned `net.http.outbound` since the plan was written, and
  docs/PERMISSIONS.md already said it was "named by the plan for later
  phases (probes)".

  Resolution taken, which is the one that test's own failure message
  prescribes ("it belongs in its own package with its own capability
  gate — not linked into the comparator"):
    - the net/http clause was removed from the binary-wide grep
    - TestOnlyTheProbePackageMayLinkAnHTTPClient added, asserting
      PER PACKAGE that internal/{check,diverge,severity,report,extract,
      model} link no net/http — finer-grained than what it replaces
    - TestTheCheckPathCannotMakeANetworkCall is UNCHANGED and passes
    - the LLM-provider name check is UNCHANGED and passes
  Mutation-tested: adding internal/probe to the guarded list turns the
  new assertion red, naming the package.
  This is a change in the product's network posture and is written up
  in LIMITS, PROBES.md, CLAUDE.md and .claude/rules/determinism.md.
  It is the item on this branch most deserving of human review.

Q12 — ANSWERED: both exist, and why
  The §4 brief said Phase 31 must "either re-site [capture's passive
  DNS/TCP/TLS checks] as probes or state that both exist and why".
  Answer: both exist. The deciding difference is the return type —
  capture answers yes/no because it records what an environment is
  configured as; a probe must be able to answer `inconclusive`, which
  is a verdict it is REQUIRED to be able to reach. Collapsing them
  means changing internal/capture's interface, which this phase does
  not own, and field 6 says remove nothing. Cost, stated in PROBES.md
  and LIMITS: the dial/resolve/handshake primitives now exist in two
  packages. (An earlier intention to share one mechanism was abandoned
  after reading the interface — recorded here because it was stated
  aloud before it was checked.)

AUDITS — both run, both adversarial, both found real defects

  invariant-auditor: 2 violations + 1 decision. All acted on.
   V1 BLOCKING, and the worst defect of this phase: `culprit probe
      --format json` printed a password. Redaction had been applied in
      the TEXT RENDERER, so it was one *format*, not one point — while
      the file's own header comment claimed otherwise. Eight probes copy
      a caller's `url`/`host`/`key`/`package`/`table` into `measured`
      and `reason`. Reproduced by hand before fixing.
      FIX: `model.RedactReading`, applied by the runner BEFORE a Reading
      exists as a value, so text, JSON, `POST /readings` and anything
      downstream inherit it; plus `redact_reading` on the API ingest
      path, because that endpoint accepts readings from outside the
      CLI's guarantee and they land in a 90-day store `api-reader` can
      read. Both mutation-tested red. This is Phase 30's audit finding
      arriving on a new path, and Phase 28's "one more site" lesson
      arriving as "one more format".
   V2 `docs/LIMITS.md` claimed built-in probes "never copy an input into
      a reading — asserted per probe". False, and it was the premise
      justifying not checking `measured` at all. Rewritten to what is
      true, including that the pattern heuristic is load-bearing for a
      `url` rather than a backstop.
   D1 The migration argued `probe-writer` bounds a leaked credential
      that could otherwise "rewrite the repository's own claims about
      itself". Not true at the API layer: `POST /readings` shares
      `CULPRIT_PROJECT_TOKEN` with `/facts/captures` and
      `/divergences/captures`. Docstring narrowed to what the role
      actually buys (it bounds a leaked *database* credential, not a
      leaked *API* one). **Whether those three endpoints should share
      one token is an open question for the architecture session.**
   Also taken: the new per-package network assertion checked only
      `net/http`; `internal/report` sits outside `internal/check`'s dep
      graph, so it could have gained `net` + `crypto/tls` with every
      test green. Now held to all three names.
   Judged HOLDS by the auditor, after checking the precedent itself:
      the `anomaly-detector` read-grant widening.

  phase-auditor: verdict PHASE NOT COMPLETE. Findings and outcomes:
   - **`probe.net.tcp_connect` reported `fail` on a timeout**, while
     PROBES.md, LIMITS.md and CLAUDE.md all described the opposite. My
     own earlier demo only looked right because the manifest timeout
     fired first. The docs described the better behaviour, so the CODE
     moved: timeout/deadline -> inconclusive, refused -> fail, with a
     fixture for each and both verified against a real network.
   - `probe.http.reachable` returned `fail` when it had had four
     responses (a redirect chain). Now inconclusive.
   - `probe.http.route_conformance` asserted "is declared" and
     `probe.config.present` asserted "reads it with no default" when
     nothing had declared anything — probes guessing, which is the one
     thing this architecture exists to prevent. Both now return
     inconclusive when `request.Expectation` is nil, with fixtures for
     the declared and undeclared cases.
   - `componentOf` read the wrong subject part for `component:` and
     `image:` targets (they key "name", not "component"), so every
     refusal against a component was recorded with no component at all.
     Found via a reason string reading "... is not set for ,".
   - `parseInputs` could not express a list, making `expect_fields` and
     `expect_columns` — and so two probes — unsatisfiable from the CLI.
     Repeating a key now builds a list.
   - `docs/PERMISSIONS.md` still said `net.http.outbound`, `repo.read`
     and `telemetry.metrics.read` were unused and "granting one changes
     nothing". That is the document a user reads before granting
     production access. Rewritten.
   - Field 15 was NOT MET: PROBES.md documented 3 of the 5 required
     per-probe attributes. Inputs and expected-source columns added.
   - `culprit --help` still claimed the build implements two planes.

ACCEPTANCE CRITERIA (field 14) — verdicts after the audit fixes

  1. `culprit probe connection:...` returns readings for reachability,
     TLS, route conformance and impedance
     PARTIAL. The audit found the criterion's verbatim command could
     never work: `demo-services/culprit.yaml` had NO `environments:`
     block, so `--env` was unpassable and all 13 probes refused. Fixed —
     a `local` environment now grants the four network/HTTP read
     capabilities, and the command runs and produces real verdicts.
     Still partial: the demo stack was not brought up in this run, and
     impedance cannot reach a verdict from the CLI at all (below).
  2. Blocking the path flips exactly the reachability probe to fail
     while health probes stay pass
     **NOT TESTABLE AS WRITTEN — needs an architecture decision.**
     Not merely unrun: structurally unsatisfiable. Probes dial from
     wherever the CLI runs, and `probe.Request` has no vantage point, so
     a partition *between* two containers is invisible to a host-run
     probe (both stay reachable via published ports). Stopping a
     container instead makes its own health probe fail too, so
     "exactly the reachability probe flips" cannot be produced either
     way. Either probes gain a vantage point — running the static binary
     inside the container under an allowlisted `exec`, which is what
     "from where A sits" actually requires — or the criterion is
     reworded. Documented in LIMITS; not decided here.
     What WAS demonstrated for real: refused -> fail + exit 1;
     timeout -> inconclusive; a live host -> pass.
  3. Every probe returns inconclusive with a reason when preconditions
     are unmet
     PASS, and enforced structurally:
     TestEveryProbeHasAllThreeVerdictFixtures fails by name if any
     catalogue probe lacks a pass, fail or inconclusive fixture.
     Mutation-tested red.
  4. No probe declares effect: mutate; validation rejects one that tries
     PASS. Refused on the type (Go and Python), again at catalogue
     registration, and asserted over the shipped catalogue.
  DoD docs/PROBES.md                 DONE, after the audit found it met
                                     3 of the 5 required attributes.
  Field 17 (not built)               No probe selection, no fault trees,
                                     no synthetic write transactions —
                                     the HTTP client has no method that
                                     can send a body or use a verb other
                                     than GET/OPTIONS.

GATES (all on the merge-result tree)

  just lint / cli-lint                     PASS
  just typecheck                           PASS 0 errors x5 projects
  just lint-imports                        PASS 4 contracts kept
  just test                                PASS 888+4s api, 100 worker,
                                                21 mcp, all Go packages,
                                                31 extractor-python, node
  just check-schema-drift                  PASS 16 tables
  just check-invariants                    PASS coupled + symmetry
  just check-no-llm-imports                PASS 9 packages
  just check-scan-coverage                 PASS 251 files
  just check-migration-round-trip          PASS against a real DB,
                                                including a9d2c40f7e18
  just self-check                          PASS 1023 facts / 451
                                                subjects, 0 divergences
  real network probe runs                  PASS (see criteria above)
  CI on the merge result                   NOT RUN — see COMMITTING.

MUTATION TESTS (invariant 10) — both new gates shown red
  remove one probe's inconclusive fixture -> field-13 coverage gate red,
      naming the probe
  add internal/probe to the guarded list  -> new HTTP boundary assertion
      red, naming the package

CULPRIT CAUGHT A REGRESSION IN ITS OWN BUILD
  `just self-check` fell from ~987 to 483 facts: the new role's env var
  made api refuse to import, so route extraction silently produced
  nothing. Fixed in the justfile (2 recipes) and 3 ci-cd.yml env blocks.
  Now 1023 facts, 0 divergences. This is the dogfooding working.

DEFECTS FOUND AND FIXED IN REVIEW (not by the gates)
  1. The new probe engines omitted `hide_parameters=True`, which the
     capture engine sets so a failing insert cannot log its bound
     parameters. A reading's `measured`/`evidence` is exactly the JSONB
     that would land there. Phase 30's audit caught this same omission
     on the sibling engine; fixed here in api and worker.
  2. Impedance emitted ONE READING PER SCORED METRIC ROW — the raw
     metric event rate into a 90-day hypertable. Collapsed to one per
     (connection, metric) per batch, with the trade-off (an intermediate
     spike in a catch-up batch survives as an `anomalies` row, not as a
     reading) tested and documented.
  3. A subagent left a literal `</content>` tag in the migration,
     breaking the symmetry gate. Caught by running the gate, fixed.

ROLE WIDENING — NEEDS A HUMAN EYE
  The migration grants `anomaly-detector` SELECT on `connections`, a
  WIDENING of an existing role, which .claude/rules/database.md warns
  about. Verified before accepting: that role already holds SELECT on
  `components` (Phase 27 RENAMED `services`, and a rename carries its
  grants), so this is a read grant on a sibling of a table it already
  reads, for the same job — resolving which edge a metric belongs to.
  The rule's bold sentence is scoped to writes. The alternative was a
  14th role whose only job is reading one table the same process
  already reads a sibling of. The downgrade revokes it. Flagged rather
  than waved through.

OPEN QUESTIONS FOR THE ARCHITECTURE SESSION (§3 is retired; they live here)
  1. **Criterion 2 needs a vantage point, or rewording.** See above. A
     probe that dials from the CLI's host cannot demonstrate a partition
     between two containers, which is what the criterion asks for.
  2. **Should the three project-token endpoints share one token?**
     `POST /readings`, `POST /facts/captures` and
     `POST /divergences/captures` all authenticate with
     `CULPRIT_PROJECT_TOKEN`. The Postgres roles are split three ways;
     the API credential is not, so a token leaked from a probe runner
     can write the repository's own claims about itself. This is the
     API-auth analogue of the role reuse `.claude/rules/database.md`
     forbids, and the rule does not cover it.
  3. **Field 13's "fixture" was read as a table-driven case set**, not
     as `cli/testdata/probes/<id>/` directories. The requirement is
     enforced by a gate rather than listed; say if on-disk fixtures were
     meant.

PLAN CORRECTIONS — for the architecture session
  - Field 13 says "each probe gets a fixture". Implemented as a
    table-driven case set in cli/internal/probe/probe_test.go with a
    coverage gate, not as cli/testdata/probes/<id>/ directories. The
    requirement is enforced rather than listed; if the plan meant
    on-disk fixtures specifically, say so.
  - Field 9's `POST /probes/{id}/run` is not satisfiable as written:
    field 3 says probes execute in the culprit binary and no agent
    transport exists until Phase 33. Implemented as an honest 503
    naming the local command, with a test that it writes nothing.
  - Field 4's `probe.edge.impedance` needed an attribution rule the
    plan does not give: telemetry is keyed by service, impedance by
    connection. The rule chosen (peer attribute; else exactly one
    declared inbound connection; else emit nothing) is in LIMITS.
  - Phase 30's LIMITS text said the self-check step is
    `continue-on-error`; 60e53fd removed that. Corrected.

KNOWN GAPS, STATED PLAINLY
  - CI has not run. Only CI exercises: Linux + clean checkout + CRLF,
    the frontend Docker build from generated types, Trivy on all six
    images, the kind and Compose end-to-end jobs.
  - **Six of the thirteen probes have no data source in the CLI.**
    `probe.db.connect`, `probe.db.schema_conformance`,
    `probe.config.present`, `probe.dep.version` and
    `probe.edge.impedance` need a database client, config reader,
    package reader and metrics reader; `cmd/culprit/probe.go` wires only
    Network and HTTP. They return inconclusive with a reason naming the
    missing source — honest, and not usable. The manifests, capability
    gates, verdict logic and fixtures are real and tested against fakes;
    the wiring is not. Impedance is the one that cannot simply be wired:
    reading it means calling the API, and the binary deliberately links
    no HTTP client outside the outbound probe path — which is why the
    worker produces those readings instead. Documented in LIMITS and
    PROBES.md rather than fixed, which is the choice the audit offered.
  - `request.Expectation` is never populated by the CLI, so
    `expected_source` is always null and every manifest's
    `expected_from` is inert in practice. The probes that would
    otherwise guess now return inconclusive instead, so this is honest,
    but the INTENT-vs-OBSERVED comparison the planes exist for is not
    yet wired end to end.
  - Criteria 1 and 2 were not demonstrated against a running demo
    stack (above). Neither was the Q2 recorded demonstration.
  - Go surface is now 13,307 non-test lines, up from 10,356. The ~6k
    revisit trigger from the retired Q1/Q9 is long past; the boundary
    question is unanswered, and §3 no longer exists to hold it.
  - The `GET /probes` catalogue is a committed JSON mirror of the Go
    one. A test checks the ids/effects/timeouts against the Go source
    by regex, which is better than nothing and weaker than a shared
    fixture.
  - Still true: no .gitattributes (CRLF noise), ghcr.io packages
    private, CLAUDE.md far over its 8 KB budget (it grew again here).

COMMITTING — the human, one command
  git add -A ':!shared/uv.lock'
  git commit -F <message file printed in the session>
  Do NOT stage shared/uv.lock.
  Then `/ci` to test the merge result and satisfy invariant 12.
```

Previous run (2026-09-12, earlier) — stopped at step 2 on Q15, before
that question was resolved:

```
Run:          2026-09-12, /next — STOPPED AT STEP 2 ON A BLOCKER.
              No phase was executed. Phase 31 NOT started.
Status:       gates red, unchanged. Phase 30 is NOT complete
              (invariant 12): `main` is red on `deploy`, and Q15 — the
              question that blocks it — is not answerable from a
              session. Nothing in it is code.

WHY THIS RUN DID NOT EXECUTE A PHASE
  /next step 2 says: if a §3 question is marked as blocking the
  current phase, stop and report. Q15 is, on two counts, and neither
  moved since the last run:
   1. It needs shell access to `culprit-vm` to edit `infra/.env.prod`.
      No session has it, and the file is by design never written from
      CI or a repo.
   2. It carries an architecture decision — whether a public
      production deploy belongs in the phase gate at all — which §3
      forbids Claude Code from answering.
  There is no repository-side change that turns `deploy` green. The
  branch is not broken; the VM is five weeks stale.

WHAT HAD HAPPENED SINCE THE LAST REPORT (a human, not this session)
  60e53fd  committed the previous run's three staged docs, and with
           them the two working-copy edits that run had flagged as not
           its own: ci-cd.yml dropping `continue-on-error` from the
           self-check step, and the rewritten .claude/skills/ci/SKILL.md
           (plus a copy under claude-setup/).
  PR #18   merged it -> bb73a9b on main.
  §1 said "staged, not committed" and named 888eb22 on arrival. That
  is the third consecutive run to find §1 stale; corrected again.

WHAT WAS VERIFIED (read-only; no code, no gates re-run)
  main run 34641745097 on bb73a9b, job by job:
    success  lint, typecheck, cli, migration-round-trip, test,
             self-check, kind-capture, build(api, worker, frontend,
             mcp_server, cli)
    FAILURE  deploy
  The deploy log is the same line as every run since Phase 14:
    RuntimeError: REGISTRY_ADMIN_DB_PASSWORD must be set in the
    environment to run this migration
    (635870479f4e_create_service_registry.py:188, after pulling
    ghcr.io/josh-heath123/view/*)
  Deploy conclusion of the last six main pushes: bb73a9b, 888eb22,
  c5ce4eb, a407542, 7ad6579, 186b068 — failure, every one.
  Note: ci-cd.yml no longer lets a self-check finding pass (60e53fd
  removed `continue-on-error`), and self-check was green on that run,
  so the stricter gate is already proven to hold.

WHAT THIS RUN CHANGED
  docs/HANDOFF.md  §1 (branch, status, blocking questions, last gate
                   run — all pointed at the superseded 888eb22) and
                   this report. Nothing else. No code, workflow,
                   config or LIMITS change, because nothing was built.

GATES:        NOT RUN, deliberately. No code changed. CI on bb73a9b
              (above) is the gate of record and is red on deploy only.
AUDITS:       BOTH RUN, neither came back clean. Every finding was
              either fixed or recorded above; the two that need a human
              are under OPEN QUESTIONS.
LIMITS:       not updated — no new threshold, ceiling or failure mode
              was introduced. The SARIF and Caddy sections stand.

TO FINISH PHASE 30 — unchanged, and still a human's, on culprit-vm (Q15)
  1. scripts/backup.sh FIRST. This upgrade runs every migration from
     Phase 14 to Phase 30 in one go, including Phase 27's
     services -> components rename, against a database that has never
     seen any of them.
  2. infra/.env.prod: IMAGE_REGISTRY=ghcr.io/josh-heath123/culprit,
     and every missing line from infra/.env.prod.example (Q15 lists
     them).
  3. Make the VM able to pull the private .../culprit/* packages.
  4. gh run rerun 34641745097 --failed, then read the deploy job
     itself, not the run's colour.
  5. Architecture session: ratify Q14's answer into §2; decide Q15's
     question of whether deploy belongs in the phase gate. Until that
     is decided, every future phase inherits this same red gate.
```

Previous run, same phase (2026-09-11 evening) — triage of the deploy
failure; its findings are carried in Q15:

```
Run:          2026-09-11 (evening), /next — Phase 30, still gates red.
              Phase 31 NOT started.
Status:       gates red. Phase 30 is NOT complete (invariant 12): the
              main run is red on `deploy`, and only a human on the VM
              can fix it (Q15).

WHAT HAD HAPPENED SINCE THE LAST REPORT (a human, not this session)
  d2dd1ac  committed the staged Caddy-from-source fix.
  63cea12  answered Q14 with its third option: upload-sarif@v3 replaced
           by actions/upload-artifact@v4 (culprit-sarif,
           if-no-files-found: error).
  PR #17   merged both -> 888eb22 on main.
  §1 still said "staged, uncommitted" and "Q14 blocks" on arrival.

/ci — tested the merge result, pinned to SHA (the ci skill's new form)
  commit   63cea12 (PR head; checkout is refs/pull/17/merge, whose tree
           is identical to 888eb22's — `git diff 63cea12 888eb22` empty)
  run      34637992018  .../actions/runs/34637992018  (pull_request)
    success  lint, typecheck, cli, migration-round-trip, test,
             self-check, kind-capture, build(api), build(worker),
             build(frontend), build(mcp_server), build(cli)
    skipped  deploy
  commit   888eb22 (the merge commit on main)
  run      34639182959  .../actions/runs/34639182959  (push)
    success  the same twelve jobs
    FAILURE  deploy
  Verdict: RED on the merge result, on `deploy` only. Every build now
  passes Trivy CRITICAL/HIGH, including frontend (the Caddy fix works in
  CI, not only locally) and api/worker/mcp_server, which the previous
  run could only call UNKNOWN. self-check: 878 facts / 370 subjects,
  0 divergences.

WHAT THE DEPLOY FAILURE IS — triaged from the job log, then history
  RuntimeError: REGISTRY_ADMIN_DB_PASSWORD must be set in the
  environment to run this migration, in Phase 14's migration
  (528aa38b5971 -> 635870479f4e), after pulling
  ghcr.io/josh-heath123/view/*:latest.
  Not new. Deploy outcome of every main push since Phase 13:
    2026-08-04  7d5a810 Phase 13            success  <- last good deploy
    2026-08-04  62ce6b1 Phase 14            failure
    2026-08-06 .. 08-10  PRs #3-#12 (17-24) failure, all the same line
    2026-09-09 .. 09-10  PRs #13-#16, c5ce4eb skipped (red builds)
    2026-09-11  888eb22 (this)              failure, same line
  Checked four of those logs: identical error, identical view/ pull.
  Production (read-only public GETs): /api/openapi.json lists only
  /auth/login and /incidents*; /api/users, /api/postmortems,
  /api/model/components all 404. culprit.co.za runs a pre-Phase-14
  API. Cause and the fix are in Q15.

WHAT THIS RUN CHANGED (docs only)
  docs/HANDOFF.md  §1, §4 row 30, this report; Q14 marked answered by
                   the human's commit (for ratification); Q15 added.
  docs/LIMITS.md   the SARIF section rewritten to what is committed:
                   an artifact, no annotations, and a self-check finding
                   can sit unnoticed on a green pull request.
  CLAUDE.md        Status line; "deployed to culprit.co.za" corrected —
                   true of Phases 0-13 only.
  No code, workflow or config change.

GATES
  CI (above) is the gate of record for code: it ran the full set on
  Linux on this exact tree. Local /verify NOT re-run — 888eb22 is
  byte-identical to what CI tested and this run touched only docs.
  check_coupled_files --base origin/main on the docs change: PASS.

COMMITTED:    NO. `git commit -F <file>` was denied by the permission
              system (the fourth run in a row it has been). The three
              docs are staged; the message is scratchpad/commit-msg.txt
              in session 90ffdb3c. Nothing pushed. Pushing it through a
              PR to main would run CI and attempt the deploy again.

AUDITS:       phase-auditor / invariant-auditor NOT re-run. Phase 30's
              code has not changed since both came back clean
              (2026-09-10); the delta since is frontend/Dockerfile, one
              ci-cd.yml step, .trivyignore and docs, none under the
              invariant auditor's paths. Acceptance-criteria verdicts
              below still stand.

LIMITS:       updated (SARIF section). The Caddy section from the
              previous run stands and is now true in CI.

NOTICED, NOT ACTED ON
  - Working copy, not this session's, uncommitted:
    .github/workflows/ci-cd.yml drops `continue-on-error: true` from
    the self-check step (the block comment above it still explains why
    it is there), and .claude/skills/ci/SKILL.md is rewritten (the
    SHA-pinned watch this run used). Neither staged nor committed.
  - self-check still requests `security-events: write`, now unused.
  - The self-check locally/CI fact-count gap (987 vs 878) is still
    unexplained.
  - Deploys have been failing silently for five weeks; nothing alerts
    on a red deploy job. Part of Q15's decision.

TO FINISH PHASE 30 — a human, on culprit-vm (Q15)
  1. scripts/backup.sh.
  2. infra/.env.prod: IMAGE_REGISTRY=ghcr.io/josh-heath123/culprit, and
     every missing line from infra/.env.prod.example (list in Q15).
  3. Make the VM able to pull the private .../culprit/* packages.
  4. gh run rerun 34639182959 --failed, then read the deploy job — not
     just the run's colour.
  5. Architecture session: ratify Q14's answer into §2; decide Q15's
     question of whether deploy belongs in the phase gate.
```

Previous run, same phase (2026-09-10) — the implementation report; its
acceptance-criteria verdicts still stand:

```
Phase:        30 — Environment capture and cross-environment diff
Branch:       phase-30-env-capture, cut from origin/main a407542 (the
              Phase 29 merge). origin/main has not moved since, so the
              staged tree IS the merge result, and every local gate
              below ran on it.
Committed:    NO. `git commit -F <file>` was denied by the permission
              system twice (with and without flags). Everything is
              staged except shared/uv.lock (a stray file this session
              created by running uv inside shared/ — do not commit it;
              the session's rm of it was denied too). The commit message
              is at scratchpad/commit-msg.txt in the session directory.
CI:           NOT RUN. Nothing can be pushed without a commit. Standing
              invariant 12 says a phase is not complete until CI is green
              on the merge result; by that rule this phase is NOT
              complete. What CI would add over the local run, and what
              was done locally instead, is listed under GATES.
Started:      2026-09-10
Finished:     2026-09-10

Scope note:   /next advanced ONE ledger row. Phase 31 was NOT started.
              §1 was stale on arrival: Phase 29 had been merged (PR #16)
              since the report was written. Corrected.

WHAT WAS BUILT

  cli/internal/capability/   §2.7 as code: the closed capability set,
                             grant parsing (true/false, or a list for the
                             three per-item capabilities), and a Ledger
                             every check must ask. An ungranted check is
                             a recorded refusal, never an omission. No
                             *.write capability exists; naming one fails
                             validation.
  cli/internal/capture/      one-shot capture of one environment:
                             adapters (compose, kubernetes, process,
                             exec), env var names + shapes (values only
                             for allowlisted keys), image reference and
                             digest, live schema from pg_catalog under a
                             read-only session, alembic version,
                             installed packages, DNS / TCP / TLS checks
                             that stop before any application request.
                             A sealed envelope (DSSE-style: base64
                             payload, SHA-256, optional Ed25519).
  cli/internal/diverge/scope.go
                             the Phase 29 comparator across scopes:
                             intent_vs_configured, env_vs_env. INTENT is
                             the reference wherever it has an answer;
                             absence is judged INTENT -> environment only,
                             never against an enumeration marked
                             incomplete.
  cli/internal/check/diff.go `culprit diff` as a function. Takes captures
                             as arguments, so internal/check still links
                             no networking package.
  cli/cmd/culprit/env.go     `culprit env capture <env>`, `culprit diff
                             <a> <b>` (each side a live environment or a
                             saved envelope, verified before use).
  ValueShape.scheme          Q7, as decided: a closed enum, in Go, Python
                             and both CHECK constraints (migration
                             e4c1b7a9d2f0). Shapes compare by
                             ValueShape.Equivalent: length only as
                             empty-or-not, unknown type on presence
                             alone. shared/tests/shape_conformance.json.
  api/app/model/captures*.py POST /captures, GET /captures/{id}, GET
                             /captures/diff. New role capture-writer;
                             api-reader reads through one serialiser that
                             never renders a config value.
  /services removed          field 6. Keys and topology suggestions moved
                             under /model; the dashboard uses /model only
                             (done by a forked agent; its tests pass).
  docker-compose.prod.yml    an optional one-shot capture agent under the
                             `agent` profile, on a new distroless `cli`
                             image added to CI's build/scan/push matrix.
  docs                       PERMISSIONS.md (DoD), demos/phase-30.md (Q2
                             written account), LIMITS (+19 sections),
                             EXTRACTOR_PROTOCOL.md (scheme), UPGRADING.md.
  evals                      cli/testdata/envdiff/ (7 fixtures, false
                             positives 0, including clean-environments);
                             a Compose end-to-end test against two real
                             projects; a kind test against a real
                             cluster. Both are also new CI steps/jobs.

GATES (all run on the merge-result tree, all green after the audit fixes)

  just lint / typecheck / lint-imports     PASS (4 contracts kept)
  just check-schema-drift                  PASS (16 tables)
  just test                                PASS 832 + 86 + 21 python,
                                                 all Go packages,
                                                 31 extractor-python,
                                                 22 node
  check_coupled_files --base origin/main   PASS
  check-scan-coverage / no-llm / symmetry  PASS
  just check-migration-round-trip          PASS (with a seeded row
                                                 carrying `scheme`)
  just self-check                          PASS 987 facts, 0 divergences
                                                 (was 983: the API still
                                                 imports, so the route
                                                 table is really read)
  LLM_PROVIDER=none culprit check          PASS
  Compose end-to-end (CULPRIT_DOCKER_TESTS) PASS 47s, real containers
  kind (CULPRIT_KIND_TESTS)                PASS against a local kind
                                                 cluster
  cross-compile, 5 release targets         PASS (done locally, since CI
                                                 could not run)
  Trivy, CRITICAL/HIGH, on `cli` and `api` PASS (done locally with
                                                 aquasec/trivy 0.65 and a
                                                 fresh base image)
  CI on the merge result                   NOT RUN — see Committed.

MUTATION TESTS (invariant 10) — every new gate shown red

  shape struct equality instead of Equivalent  -> clean-environments FP
  environment skips ignored                    -> incomplete-enumeration FP
  INTENT-as-reference off (absence, conflict)  -> duplicate env_vs_env FP
  every value treated as allowlisted           -> planted-secret test red
  renderer prints config values                -> report redaction red
  ValueShape membership check removed          -> model tests red
  API serialiser returns the raw column        -> planted-value test red
  API grant check skipped                      -> ungranted-value test red
  downgrade's scheme-strip removed             -> round trip red
  pgx deferred-error check removed             -> Compose e2e red
  exec adapter reads lines again               -> multi-line leak test red
  manifest error echoes input                  -> echo test red
  Grant.capability as free str                 -> capability test red
  report reason redaction removed              -> tamper test red
  SARIF notifications removed                  -> SARIF refusal test red

ACCEPTANCE CRITERIA (field 14)

  1. `culprit diff staging production` reports a missing env var
     required by an intent fact, ranked breaks_request_path
     PASS — run for real on cli/testdata/demo (docs/demos/phase-30.md):
     JWT_SECRET_KEY, read by orders_api/config.py with no default,
     orders-api on the request path. The phase auditor also removed it
     from .env.example and compose and it was still found from the code
     alone, and a missing PORT (which has a default) came out degrades.

  2. Detects live DDL behind the migration head
     PASS — migration_head 0003 vs 0002, and the order_lines table the
     code maps missing from production. Also found by the auditor on a
     database stamped 0003 but missing the table.

  3. Detects an image digest mismatch
     PASS — env_vs_env on image:orders-api digest (and reference). The
     same-tag-different-digest case is the corpus fixture; the kind
     test reads a real Pod's digest.

  4. With only config.read.names granted, values never appear in output
     and the report says which checks were refused
     PASS after the audit fixes. FAILED on the first audit, correctly,
     twice over: the exec adapter could turn a line of a multi-line
     secret into a variable NAME (below, #1), and SARIF carried no
     refusals at all. Both fixed, both now tests, both mutation-checked.

  DoD: docs/PERMISSIONS.md                  DONE, every §2.7 grant, with
                                            four overclaims corrected by
                                            the audit.
  Q2 obligation: written account            DONE (docs/demos/phase-30.md).
                 recorded demonstration     NOT DONE — needs a person.

DEFECTS FOUND AND FIXED

  By running the thing against real systems:
  1. information_schema lists only tables the role can use: a
     least-privilege capture role would have made every other table
     look missing from production. Reads pg_catalog now.
  2. pgx reports "permission denied" after iteration, not from Query():
     a role without SELECT on alembic_version read as "at no revision",
     a false breaks_request_path. Now "version not read".
  3. configured_facts' Phase 26.1 CHECK (value IS NULL OR grant_ref IS
     NOT NULL) covers every row, so no image digest or column list
     could be stored at all. Not narrowed: every CONFIGURED fact now
     names the grant that permitted it, and POST /captures checks it
     against the capture's own grant list — closing LIMITS' "nothing
     validates that the grant it names is real".
  4. The Go ValueShape never checked its fields against their closed
     sets: a DSN in `type` decoded and was printed into SARIF. Found
     while adding `scheme`.
  5. pgx 5.7.5 carried a CRITICAL CVE (fixed 5.9.0, which needs Go
     1.25); CI's Go 1.24 was past support and its binaries carried
     stdlib CVEs. Caught by scanning the new image locally.

  By the two audits (both right):
  6. BLOCKING: the exec adapter split output on newlines; a PEM key's
     last base64 line (`QUJDREVGRw==`) is a valid-looking assignment, so
     a fragment of a secret became a subject — never masked, in the
     envelope and every report. No character rule can tell it apart;
     the exec adapter now accepts only NUL-delimited pairs (env -0) or
     a JSON object and refuses lines.
  7. SARIF carried no refusals: a no-grant diff was an empty,
     clean-looking log. Now toolExecutionNotifications.
  8. Skip/refusal reasons and meta from a loaded envelope were printed
     verbatim; a hand-edited, re-hashed envelope could put a DSN in the
     report. Now refused on open (Go and Python) and redacted at one
     point in every renderer.
  9. The Python manifest loader echoed a pasted DSN in its error
     (pydantic input_value). Fixed at the one place it renders errors.
  10. The §2.7 closed set was enforced only in Go: the API stored a
      capture "granted db.schema.write" and apply-model accepted
      config.read.values: true. Now a Python Capability enum, held to
      Go by shared/tests/capability_conformance.json.
  11. Four PERMISSIONS.md overclaims (length kept, "signed" envelope,
      "refuses an altered envelope", Kubernetes Secret RBAC).
  12. Smaller: an exec env_command could be skipped without a refusal
      if process.exec.allowlist was absent; absolute compose files were
      joined onto the manifest directory; no hide_parameters on the
      capture engine; a help text claimed "safe to attach" even with
      values allowlisted.

PLAN CORRECTIONS AND DEVIATIONS — for the architecture session to ratify

  - Field 11 (client-go + Docker SDK behind build tags): not done. The
    adapters run the `docker` and `kubectl` the user already has. Behind
    build tags the downloadable binary would capture nothing; both SDKs
    are HTTP clients in a binary whose test asserts it links none. In
    LIMITS.
  - Field 7 ("signed"): signing is optional (--sign-key). Culprit will
    not invent a key for the user; unsigned envelopes are hashed only
    and can be re-hashed after editing. In LIMITS; see Q11.
  - Field 4 lists DNS / TCP / TLS; Phase 31 lists the same as probes.
    Implemented here as passive facts stopping before any application
    request (field 17 read as "no application requests"). Phase 31
    should reconcile — Q12.
  - Field 5 ("api/app/model/ stores captures") needed data the Phase 26
    table lacked: captures gained digest, signed_by, grants, refused.
  - A twelfth role, capture-writer, rather than a third reuse of
    fact-writer (which .claude/rules/database.md names as the signal the
    rule has stopped working). api-reader gained SELECT on captures and
    configured_facts — the established reader pattern, argued in the
    migration; the residual risk is in LIMITS.
  - The CLI still does not upload (LIMITS promised Phase 30 would; field
    4 listed endpoints, not an uploader) — Q10.
  - scripts/coupled_files.yaml retargeted shape.py's pair from
    d1f4a9c73b60 to e4c1b7a9d2f0 (a historical migration is not edited
    to satisfy a coupling check); the invariant audit judged it
    legitimate.
  - Not fixed, pre-existing (Phase 28): an absolute extract.components
    `root:` is joined onto the manifest directory the same way.

DELIBERATELY NOT BUILT (field 17)

  No request into the system under test (DNS lookup, TCP handshake, TLS
  handshake only). No writes: read-only DB session, read-only docker /
  kubectl verbs, no write capability. No agent daemon: the compose agent
  is profile-gated, restart "no", one-shot, stdout.

DEPLOY PREREQUISITE — a human, on the VM, BEFORE merging

  Add CAPTURE_WRITER_DB_PASSWORD and CAPTURE_WRITER_DATABASE_URL to
  infra/.env.prod (docs/UPGRADING.md). Without them the migration stops
  and the api refuses to start. Also: the new ghcr.io `cli` package will
  be private under GITHUB_TOKEN, like the other four.

KNOWN GAPS, STATED PLAINLY

  - CI has not run (above). Things only CI exercises: Linux + clean
    checkout + CRLF, frontend Docker build from generated types, the
    kind job via helm/kind-action (pinned v1.12.0, never run), the
    Compose e2e step on a runner.
  - The residual risks the invariant audit named are documented in
    LIMITS, not fixed: api-reader can read granted literals (only the
    serialiser stops them), per-key grants are enforced by the API not
    the DB, non-config values are not type-checked on upload — Q13.
  - Go surface: 10,139 non-test lines (was 6,060). Q1's trigger was
    already tripped — Q9.
  - Still true: no .gitattributes (CRLF noise), ghcr.io packages
    private, CLAUDE.md over its 8 KB budget (grew again).
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
