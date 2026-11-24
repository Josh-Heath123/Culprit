# Culprit — field-readiness plan (Phase 44)

Written 2026-11-21 by the architecture session, at the owner's request. It is
the plan of record after `docs/DELIVERY_PLAN.md`, and the master brief for an
exhaustive audit and optimisation of the whole application before the first
field trial. Read it whole at the start of every run of Phase 44, after
`docs/HANDOFF.md`.

---

## §1. Why this phase, and what "ready" means

Culprit is a deterministic diagnostic and fault-isolation engine: "a
multimeter for software".
- **What it does:** it compares three planes — INTENT, CONFIGURED and
  OBSERVED — and reports where two of them disagree. It then walks the system
  model to isolate the root fault, runs read-only probes, and closes the loop
  with `culprit verify`, whose verdicts are `verified`, `not_resolved`,
  `changed_underneath` and `inconclusive`.
- **What it promises:** the machine establishes facts and an LLM only
  narrates them, so Culprit stays useful with the AI layer removed.
- **Who it is for:** solo developers and small teams without SRE staff. They
  use it directly, or through an AI coding agent over MCP, in development and
  CI, and in production under least privilege.

The next step is a field trial: the owner runs Culprit against an open-source
project he neither wrote nor controls. That is also Phase 29's condition for
publishing. This phase makes the application ready for that trial, and proves
it.

**Ready for the field trial means all of these, and nothing less:**

1. **Installable by a newcomer.** Someone new can install Culprit from source
   and get a correct first result on an unfamiliar repository by following
   `docs/INSTALL.md` and `docs/GUIDE.md` alone, on Linux and on Windows.
2. **Never states a wrong fact.** On a project Culprit has never seen, it
   never presents a wrong fact as a fact. What it cannot see, it says it
   cannot see.
3. **Never writes or leaks.** It never writes to, changes, or leaks from the
   system it diagnoses. Every secret it reads stays redacted on every way out.
4. **Repeatable.** The same inputs give the same record and the same verdict.
5. **Fails cleanly.** Every failure a field trial can plausibly hit ends in a
   clear, actionable message and a consistent state, never a stack trace or a
   silent wrong answer.
6. **Clear interfaces.** The CLI output, the dashboard and the MCP responses
   are clear, consistent with the identity, and usable at desktop, tablet and
   phone widths.
7. **Proven.** Every claim above is backed by something that ran.

A successful build, or green CI, is not readiness.

---

## §2. Rules for every run of this phase

These rules add to `docs/HANDOFF.md`'s header, the standing invariants
(`docs/DIAGNOSTIC_PLAN.md` §3), D1–D8 and P1–P8, all of which still bind.
Where this section and the handoff differ, the handoff wins: raise the
difference (handoff §6).

### Inspect before you change

- **Read the code behind every claim.** A docstring, a doc or a plan is not
  the code.
- **Reproduce before you call it a bug.** Before you call something dead,
  `git grep` every caller, route, workflow and test that names it.
- **Map the repository as it is,** not as the docs describe it. Where the two
  differ, the difference is itself a finding.

### Preserve what Culprit is

- **Remove nothing.** No feature, command, route, probe, screen or API
  endpoint is removed. Where something looks obsolete (see §4.1, legacy
  surfaces), record it as a finding with the evidence: removing it is the
  owner's decision.
- **Keep what Culprit claims.** Do not change:
  - a verdict rule;
  - the determinism boundary;
  - what counts as evidence;
  - the three planes;
  - any D-rule.
- **Never loosen a gate.** That means:
  - no `continue-on-error`;
  - no skipped or `xfail` test;
  - no weakened assertion;
  - no widened budget;
  - no retry that hides a flake.

  A flaky check is a defect, and it gets its cause found (D6).
- **Never widen privilege.** Add no `mutate`-effect probe, no `*.write`
  capability and no database grant.
- **Never edit an applied migration.** A schema change gets a new migration,
  round-trip tested.
- **Ask before adding anything.** Raise any new dependency, service or tool
  first (§6), and prefer the standard library and what is already in the
  lockfiles.
- **Change code only for a recorded finding,** and only as much as the
  finding needs. Do not rewrite working code for style.

### Prove every change

- **Show the test fail first.** A fix lands with a test that failed before it
  (shown red in the report) and passes after it. A new or changed gate lands
  with a mutation that turns it red.
- **Two readers of one value read one value.** A rule implemented in both Go
  and Python is held by a shared fixture under `shared/tests/`, not by two
  lists.
- **Keep the docs true.** Every behaviour change updates `docs/LIMITS.md`
  (invariant 7). Where users must act, it also updates `docs/UPGRADING.md`.
  Docs and code change in the same commit.
- **Never claim what did not run.** Never write "works", "fixed" or "verified"
  for something that did not run. Every finding and every result carries one
  of three labels:
  - **VERIFIED:** reproduced or tested here, with the command and its output;
  - **RISK:** reasoned from the code, not reproduced;
  - **UNTESTED:** could not be run here, with the reason (needs Linux, Docker,
    Kubernetes, credentials, a third-party system, or the owner).

### Work within the machine

- **The laptop runs out of memory.**
  - Run gates one at a time, in the foreground.
  - Never run the fault library, or the demo stack with its faults, locally:
    they run in CI.
  - Run the quickstart stack only on its own, and bring it down afterwards.
  - Leave no background watcher running. When a CI run is long, record its
    id and poll it in the foreground, or stop and let the review read it.
- **Linux CI is the reference.** Windows is the second platform the owner
  uses, and a difference between the two is a finding.
- **A fresh clone is a different machine.** Before calling anything done,
  verify it again from a clean clone.

### Stop instead of deciding

- **Raise these in handoff §3 and §6, and decide none of them yourself:**
  - anything architectural;
  - anything that changes what Culprit claims;
  - any visual change beyond the identity in `docs/DELIVERY_PLAN.md` §2;
  - any fix that needs the owner's credentials, accounts or money, or a
    third-party system;
  - any destructive operation.
- **Never do any of these:**
  - delete data;
  - drop a table;
  - reset a database other than a disposable test container;
  - deploy, publish, release, or cut a tag.
- **One part per run.** Each run does one part of this phase and stops (the
  `/next` rule). The pull request stays a draft until the run report is
  committed. The owner merges after the architecture review.

---

## §3. How the phase runs

- **Part 1, the audit (§4).**
  - Read, run and record, with no product change.
  - It writes the findings register (§5) and proposes batches, then stops for
    review.
  - The review rules on every finding: fix it (and in which batch), defer it
    with a LIMITS entry, reject it with a reason, or put it to the owner.
- **Parts 2 to n, the batches.**
  - Each batch is its own branch and pull request, briefed in §6 by the
    review before it.
  - They run in the order the review sets, normally:
    1. S1 correctness and security;
    2. reliability and edge cases;
    3. the backend and performance;
    4. the interface, with before-and-after screenshots for the owner to
       approve;
    5. documentation and the first-run experience.
  - A batch stays small enough to review: one area, or about ten findings.
- **The last part, readiness (§7).** The regression pass, the fresh-clone
  walkthroughs, the readiness assessment and the field-trial runbook.

---

## §4. Part 1 — the audit (brief, 2026-11-21)

**Setup.**
- Work on branch `phase-44-audit`, cut from `origin/main`. Its first commit is
  the review (handoff §1 names the patch).
- **Change no product code, test or workflow in this part.** Commit only this
  plan's §5 and the handoff report.
- Keep scratch scripts, screenshots, logs and probe output outside the
  repository, in `../audit-44/` (the folder above it), where the architecture
  session can read them.

**Step 0.**
- **Attribute `main`'s red push run first.** Run 44881325932 on `ddb275e`
  failed `e2e (stub)` at the step "The agent's Kubernetes and systemd
  recipes", so `narration-parity` was skipped and `gate` failed. The same tree
  passed on PR #70's run 44880245200.
  1. Read the failed log: `gh run view 44881325932 --log-failed`.
  2. Attribute the cause.
  3. Rerun the failed jobs: `gh run rerun 44881325932 --failed`.
  4. Record both, by id.

  A flaky required check is a defect (D6), so it becomes a finding with its
  cause. If the cause is in the code, stop and raise it.
- Run the gate set once (`/verify`), one gate at a time, as the baseline.

**How to work through 4.1 to 4.9.**
- Subagents may read in parallel; nothing that runs code runs in parallel.
- For each area, record what you inspected and what you ran, not only what
  you found. The review needs to see the coverage.

### 4.1 Map the application as it is

- **Inventory every surface a user or an agent touches:**
  - each `culprit` subcommand (`init`, `intent`, `capture`, `env`, `diff`,
    `check`, `diagnose`, `probe`, `verify`, `agent`, `pair`, `mcp`), with its
    flags and exit codes;
  - each API package under `api/app/` and its authorisation;
  - each worker consumer;
  - each MCP tool, in `mcp_server/` and in `culprit mcp`;
  - each dashboard route in `frontend/src/routes/`;
  - each extractor;
  - each `just` recipe a user is told to run;
  - each workflow job.
- **For each surface, record:** what it is for, which docs describe it,
  which tests exercise it, and whether it can be reached from the documented
  journey.
- **Legacy surfaces.** Culprit began as an incident-correlation copilot
  (Phases 0–24), and Phase 32 removed the correlation engine and the
  narrative job. Code from that era remains:
  - incidents;
  - postmortems (the `PostmortemList` and `PostmortemEditor` routes);
  - RAG memory (`worker/app/rag`, `api/app/memory`);
  - anomaly detection (`worker/app/anomaly`);
  - the ingest gateway and Redis Streams.

  For each one, establish by evidence whether it is reachable, written to,
  read from, tested, documented, and coherent with the diagnostic product.
  Record one finding per surface. **Remove nothing.**

### 4.2 The core: does it work, together, and repeatably?

- **The journeys, end to end, through the real binary.** Use the demo, in CI
  wherever the stack is needed. Record each step's output.
  - The CLI loop: `init` on a repository, then `intent`, `env capture`,
    `diff`, `check`, `diagnose` and `probe`, then `verify` twice. A wrong fix
    must give `not_resolved`; the right fix must give `verified`.
  - The same loop through `culprit agent` and the control plane, seen in the
    dashboard.
  - The same loop through MCP, as an AI coding agent would drive it.
- **Determinism.** Q42 found a record that changed with Docker's random
  hostname; hunt for the rest.
  - Run each command twice on identical input and diff the canonicalised
    outputs.
  - Read for: Go map iteration, unsorted filesystem walks, `time.Now`, random
    ids, float formatting, locale and time zone, Python set order, the order
    concurrent work finishes in, and any runtime-supplied value captured as
    configuration.
  - Each source you find is a finding.
- **Go and Python parity.**
  - List every value computed in both languages: shapes, subjects,
    equivalence, the manifest readers, the per-item rule, the investigation
    model, the accuracy figure, and any others you find.
  - Record whether a shared fixture holds each one. One that is not held is a
    finding.
- **Honest absence.**
  - For each adapter (`compose`, `kubernetes`, `process`, `exec`) and each
    extractor, find inputs where it cannot see everything.
  - Check that Culprit then says so, rather than reporting absence (LIMITS:
    "an environment that could not be seen whole is never evidence of
    absence").
- **Gates that are not gates.** Cover the checks in `scripts/`, the hooks,
  the conformance fixtures, and the decision paths in
  `cli/internal/{isolate,verify,diverge,severity,capability}`.
  - Ask of each: does it have a test that can fail?
  - Sample by mutation: change a decision point, run the package's tests, and
    restore it. Record which mutations survive.

### 4.3 The backend and its architecture

- **The API (`api/app/`):**
  - input validation and the error envelope (LIMITS: a 422 does not say which
    value it refused);
  - pagination and limits;
  - transaction boundaries;
  - whether every write is idempotent under a duplicate submission;
  - concurrency, such as two verifications of one investigation;
  - authorisation and sessions: `api/app/auth`, agent tokens
    (`cli/internal/agentauth`), the last-admin guard, token grants, and
    revocation (LIMITS: a revoked ingest key works for up to 10 seconds);
  - CORS and CSRF for the dashboard;
  - what each role can read.
- **The database:**
  - the roles and grants against `docs/PERMISSIONS.md`;
  - `worker/app/db.py` against `api/app/db/models.py` (invariant 2);
  - constraints the code relies on but the schema does not enforce;
  - queries without an index on a path the dashboard or an agent calls;
  - migrations applied to a populated database.
- **The worker:**
  - behaviour when Redis, Postgres or the LLM is down, slow, or returns
    garbage;
  - retries and poison messages;
  - a restart in the middle of a job.
- **The agent and its transport** (`cli/internal/agent`, `transport`,
  `culprit agent`):
  - binding defaults, TLS and authentication;
  - what an unauthenticated caller can learn;
  - timeouts;
  - behaviour when the control plane is unreachable.
- **The boundaries:** the `lint-imports` contract, `boundarytest`, and the
  per-package `net/http` ban. Look for any path around them.
- **CI's own ordering.** On run 44881325932, every `publish` job built,
  attested and verified its image while `e2e (stub)` failed and `gate` went
  red. Whether `main`'s publish should wait for the tests is a finding:
  record what it would take, and its cost in wall time.

### 4.4 Security

- **Every way out is an exfiltration path.**
  - Put secret-bearing values (a DSN with a password, a bearer token, a
    private key) into configuration, environments and error conditions.
  - Follow them out through every exit:
    - CLI output and errors;
    - reports and SARIF;
    - the output of `diff` and `diagnose`;
    - captures, and anything a user is told is safe to attach to a bug
      report;
    - API responses, 422s included;
    - logs;
    - MCP tool results;
    - the narrator's prompt.
  - Any value that leaves unredacted is S1.
- **Untrusted input.** Treat all of these as untrusted:
  - everything read from the diagnosed system;
  - every MCP tool argument from an agent;
  - every `culprit.yaml`;
  - every extractor's output.

  Look for injection into:
  - the shell (the `exec` adapter, `docker`, `kubectl`);
  - SQL;
  - file paths (traversal);
  - templates;
  - the LLM prompt (instructions smuggled in through captured data, reaching
    the narrator or an agent through MCP).
- **Secrets and configuration:**
  - secrets in the repository and its history, the `.env` examples,
    `deploy/`, `infra/`, and the workflow logs;
  - the threat model in `SECURITY.md` against its tests;
  - the container images: their users, their ports, and Trivy's findings;
  - CodeQL;
  - the open Dependabot alerts, read through `gh api`. Dismiss nothing and
    bump nothing outside a brief.

### 4.5 Reliability and edge cases

Try each journey from 4.2 under each of these conditions, and record what
happens:
- an empty repository;
- a repository with no extractable intent;
- a monorepo at the walk's bounds;
- very large and non-UTF-8 values;
- a key with an empty value;
- Windows paths and line endings;
- `docker` or `kubectl` absent or denied;
- a container that exits mid-capture;
- network loss and timeouts during probes;
- a database that refuses the read-only session;
- clock skew between machines;
- an interrupted `verify`;
- duplicate and concurrent requests;
- a control plane restarted in the middle of an investigation.

Every failure must end in a clear message and a consistent state.

### 4.6 Performance

Measure rather than estimate, and record the machine. A finding names the
measurement and its spread, never a single sample.
- **The CLI:** start-up time and binary size.
- **Scale:** capture and walk time against environment size, since Culprit
  expects to diagnose large systems.
- **The dashboard:** bundle size and first load, using Phase 38's bundle probe
  run on Culprit's own frontend.
- **The API:**
  - latency on the pages the dashboard calls;
  - Culprit's own statement and N+1 probes, run against its own API
    (`just self-check` and the demo recipes show how).
- **CI:** wall time is about 13 minutes, and must not regress.

### 4.7 The interface

- **The dashboard.**
  - Render every route in `frontend/src/routes/` with realistic data, using
    the lightest stack the repository already has (the `e2e` stub
    configuration, or the quickstart).
  - Render each at 1440, 768 and 390 pixels wide, in the empty, loading,
    error, populated and overflowing states.
  - Save the screenshots to `../audit-44/screens/` and look at every one.
  - Judge each against:
    - the identity (`docs/DELIVERY_PLAN.md` §2, I1–I7): the plum page, cream
      text, violet for fills and selection, lime only for the culprit, Inter
      and JetBrains Mono, and motion of 150–220 ms with none under reduced
      motion;
    - WCAG 2.2 AA contrast and keyboard use;
    - visual hierarchy, spacing and alignment;
    - consistency between components;
    - whether each workflow is obvious to someone using it for the first
      time.
  - `check-frontend-tokens` and the hue-separation test must stay green.
- **The CLI is an interface too.** For each subcommand, review:
  - its help text and the first-run experience;
  - the wording and layout of results and errors;
  - colour, and its absence (`NO_COLOR`, output into a pipe);
  - exit codes;
  - whether every error says what to do next.
- **MCP responses, as an agent reads them.** Are they unambiguous and bounded
  in size? Do they keep facts and narration apart?

### 4.8 Tests

- **Coverage:** per Go package (`go test -cover`), and per Python package with
  the tools already installed.
- **Gaps:**
  - critical paths with no end-to-end test;
  - tests that assert a route is exercised, but not what it returns;
  - the mutation survivors from 4.2.
- **No new test framework.**

### 4.9 Readiness for the field trial

- **The documented path.** From a clean clone, follow `docs/INSTALL.md`,
  `README.md` and `docs/GUIDE.md` exactly: on Windows here, and on Linux in
  CI. Record every place they are wrong, missing or out of date, the README's
  captures included.
- **Running it for real:**
  - version reporting;
  - what a user can safely attach to a bug report;
  - what Culprit writes, and where, on the user's machine, and how to remove
    it;
  - the control plane's logging;
  - backups (`scripts/backup.sh`), and whether a restore has ever been
    tested;
  - anything that would embarrass Culprit on a stranger's repository.
- **Deploy stays paused.** For this phase, readiness covers the self-hosted
  control plane through the quickstart.
- **The field-trial runbook.** Draft, as a finding, what it must contain:
  - Culprit run in development and CI mode only, against a project the owner
    does not control;
  - nothing written to that project;
  - how a confirmed finding is recorded.

### Before stopping

- **Have `phase-auditor` re-run a sample of the VERIFIED findings:** every S1,
  and at least ten others. Mark any it cannot reproduce as RISK.
- **Write the report in handoff §5:**
  - counts by severity and by area;
  - the coverage record;
  - the S1 and S2 findings, by number;
  - the proposed batches;
  - the questions for the owner;
  - what is in `../audit-44/`.
- **Open the pull request as a draft,** run `/ci`, and mark it ready once the
  report is committed.

**Do NOT, in this part:**
- change product code, tests, workflows or dependencies;
- run the fault library locally;
- dismiss or bump anything;
- publish, release, deploy, or touch the ruleset;
- stage `shared/uv.lock`.

---

## §5. The findings register (written by part 1)

One entry per finding, numbered from F44-001, in this form:

```
F44-NNN  <one-line title>
  Area:      core, backend, security, reliability, performance,
             interface, tests, readiness or legacy
  Severity:  S1  a wrong verdict, a leaked secret, a write to the
                 diagnosed system, data loss, or a crash on the main
                 journey
             S2  wrong or misleading output, or a failure without a
                 clear message, on a path a field trial can plausibly hit
             S3  a degraded experience, performance or documentation
             S4  polish
  Evidence:  VERIFIED, RISK or UNTESTED (and why)
  Where:     file and line, command, route or job
  Shown by:  the command and its output, or the reasoning
  Proposed:  the smallest fix, and the test that would fail first
  Risk:      what the fix could break, and how CI would catch it
  Needs:     nothing, the architecture session, or the owner (and what)
```

After the register, add:
- the coverage record: what each area inspected and what it ran;
- the proposed batches, in order;
- the questions for the owner.

### The register (part 1, 2026-11-21)

Written by the part 1 run on `phase-44-audit`. Labels follow §2: **VERIFIED**
means reproduced or tested here, with the command and its output (the
commands, scripts and outputs are in `../audit-44/`); **RISK** means
reasoned from the code and not reproduced; **UNTESTED** gives the reason.
A static fact shown by a grep or a read (a doc that names a flag the code
does not have, a `needs:` list) is VERIFIED by that read. A claim about
behaviour that was only read is RISK. Where a finding came from one of the
read-only auditors, `Detail:` names its entry in `../audit-44/notes/`,
which holds the full reasoning and the line-level evidence; the register
keeps the summary. Machine for every measurement: Windows 11, 20 logical
CPUs, Git Bash, Docker 29.6.2, Go and uv as in the repository; CI is
`ubuntu-26.04` (runner image 20261116.202.1).

**Re-run by `phase-auditor`:** 20 findings: every S1 and fourteen others
(F44-001 to -006, -008 to -012, -016, -018, -020, -024, -031, -033,
-075, -090, -091), each in a fresh copy under `../audit-44/rerun/`.
Eighteen reproduced; F44-004 and F44-006 were raised from RISK to
VERIFIED by reproducing them through the binary; F44-005 only in part
(it stays RISK); F44-020 did not reproduce and is withdrawn (it was this
run's misreading). F44-009 was confirmed from the recipe, the migration
and the log, not by running the quickstart again. Results:
`../audit-44/notes/auditor-results.md`.

#### S1

```
F44-001  `culprit intent` prints an extractor's stderr unredacted
  Area:      security
  Severity:  S1
  Evidence:  VERIFIED
  Where:     cli/internal/render/render.go:88-98 and render.JSON (skip
             reasons printed as written); cli/internal/extract (the reason
             is the extractor's first stderr line). `culprit check`
             redacts the same reason.
  Shown by:  ../audit-44/edges/leak: an extractor writes "connect failed:
             postgresql://app:LeakPw77@db.internal/app DB_PASSWORD=LeakPw88"
             to stderr and exits 3. `culprit intent` (text and --format
             json): both LeakPw77 and LeakPw88 present. `culprit check`:
             "connect failed: [redacted]db.internal/app DB_PASSWORD=LeakPw88".
             The same path carries the exception text from importing the
             user's app (F44-003). Detail: 4.4-security.md S-05.
  Proposed:  route every skip reason through RedactCredentials at the one
             place a Capture is rendered (text and JSON), as check does. Test
             first: an intent render test with a DSN in a skip reason.
  Risk:      none to behaviour; a reason a user relied on reading becomes
             partly [redacted]. The render package has no tests (F44-082).
  Needs:     nothing.

F44-002  The one credential pattern misses most common secret shapes, and
         every free-text exit depends on it
  Area:      security
  Severity:  S1
  Evidence:  VERIFIED (Python, by running it; the Go twin by the CLI's output)
  Where:     shared/culprit_model/redaction.py; cli/internal/model/redact.go:25-49
  Shown by:  redact_credentials over 15 shapes: unchanged for DB_PASSWORD=x,
             POSTGRES_PASSWORD=x (the \b fails after "_"), redis://:x@h,
             ?access_token=x, ?client_secret=x, "Authorization: Bearer x",
             sk_live_…, AIza…, glpat-…, {"password": "x"}, "password: x", a
             "/" in a URL password; "hun@ter2" leaves "ter2". Only
             password=x and user:pw@ were caught. Through the binary:
             F44-001's `culprit check --format sarif` (what code scanning
             uploads) contains DB_PASSWORD=LeakPw88. Detail: 4.4-security.md
             S-01, R-01.
  Proposed:  widen the shared pattern under the shared fixture
             (shared/tests), both languages at once; the fixture's new
             rows fail first. Prefer redacting by structure where a value
             is known (a skip reason from a subprocess) over pattern only.
  Risk:      over-redaction of non-secrets in reasons; the fixture shows it.
  Needs:     the architecture session: how wide the pattern is is a claim
             about what Culprit promises (§1, criterion 3).

F44-003  `culprit check` runs the target repository's Python and writes into
         it
  Area:      security, readiness
  Severity:  S1 (a write to the diagnosed system; criterion 3)
  Evidence:  VERIFIED
  Where:     extractors/python/culprit_extract_python/discovery.py:66-89
             (imports candidates such as config.wsgi); the GUIDE's tour
             configures the extractor without --no-import; nothing sets
             PYTHONDONTWRITEBYTECODE.
  Shown by:  the GUIDE tour, followed exactly (../audit-44/scripts/
             tour-setup.sh): `culprit check` output contains
             "config.wsgi:application: KeyError: 'DATABASE_URL'" (it executed
             api/config.py), and afterwards api/__pycache__/
             config.cpython-314.pyc exists in the project. The same through
             MCP culprit_check, whose description says it reads files only.
             The auditor also reads that a Flask app may create instance/
             with a SQLite file (.gitignore:49-53). Detail: 4.7-4.9 D-03,
             4.4-security.md S-09.
  Proposed:  set PYTHONDONTWRITEBYTECODE (and sys.dont_write_bytecode) in
             the extractor's process; say plainly, in GUIDE, MCP's
             description and EXTRACTOR_PROTOCOL, that import runs the
             user's code; decide whether the field trial runs --no-import
             only. Test first: run the extractor over a fixture with a
             config module and assert no file appears.
  Risk:      none for the bytecode; the import question changes what is
             extracted.
  Needs:     the owner: whether import (code execution) is acceptable on a
             project the owner does not control (the runbook, F44-019).

F44-004  Go's RedactReading does not walk []string, so service-chosen strings
         may leave unredacted in probe, diagnose and verify JSON and MCP
  Area:      security
  Severity:  S1
  Evidence:  VERIFIED (by phase-auditor; this run's first recipe stopped at
             "no declared response fields", ../audit-44/edges/r02)
  Where:     cli/internal/model/reading.go:368-399 (cases string,
             map[string]any, []any; default copies); measured["fields"]
             (probe/http_probes.go:309), measured["audiences"]
             (auth_probes.go:118-122). The Python twin walks lists.
  Shown by:  `culprit probe -p probe.auth.token_shape --input token=<a JWT
             whose aud is postgresql://…:pw@…> --input expect_audience=other
             --format json`, no network: measured.audiences carries the DSN
             with its password; the reason line shows [redacted]
             (../audit-44/rerun/f004/probe.json). 4.4-security.md S-02.
  Proposed:  a []string case, and a shared fixture row for a list of
             strings in a reading. Test first: RedactReading on a reading
             whose fields hold a DSN.
  Risk:      none.
  Needs:     nothing.

F44-005  Agent tasks keep probe inputs (a token included) and the symptom
         verbatim, and serve them back
  Area:      security
  Severity:  S1 if confirmed
  Evidence:  RISK (partly shown: TaskCreate's model_dump keeps
             inputs.token and a DSN unchanged, api/app/agents/service.py:225,
             schemas.py:117; storing and serving it back needs the API and
             Postgres, not run)
  Where:     api/app/agents/ (agent_tasks.spec; GET /agents/{id}/tasks/{task})
  Shown by:  4.4-security.md S-03, R-03; ../audit-44/notes/auditor-results.md.
             To raise it: one Postgres API test, POST a probe task with
             inputs.token and GET it back.
  Proposed:  refuse secret-bearing inputs on the task route, or keep them
             out of the stored spec; test first: POST a task with
             inputs.token, GET it back.
  Risk:      a task that needs a token must get it another way (the agent's
             own configuration).
  Needs:     the architecture session (how an agent gets a token).

F44-006  An agent's failure reason, and its append-only audit log, take raw
         error text, the whole symptom included
  Area:      security
  Severity:  S1
  Evidence:  VERIFIED on the agent's side (by phase-auditor); the control
             plane's agent_tasks.reason leg RISK (needs the API)
  Where:     cli/cmd/culprit/agent.go, cli/internal/agent (parseSymptom's
             error quotes the symptom; reason written to the audit log,
             stderr and agent_tasks.reason)
  Shown by:  `culprit agent --tasks tasks --once` with a diagnose task whose
             from is a DSN: audit.log and outbox/t2.json both hold 'from
             "postgresql://app:AgentPw66@db.internal/app" is not a
             component' (../audit-44/rerun/f006). 4.4-security.md S-04.
  Proposed:  redact at the one place a reason leaves the agent. Test first:
             a diagnose task whose symptom holds password=…
  Risk:      the append-only log keeps whatever is already in it.
  Needs:     nothing.
```

#### Step 0, then S2

```
F44-007  Step 0: main's red push run 44881325932 was a kind image import
         that left nothing on the node
  Area:      tests (CI reliability)
  Severity:  S3 (a flaky required check, D6; no product effect)
  Evidence:  VERIFIED (both logs read; rerun green); cause UNTESTED
  Where:     scripts/check_agent_recipes.sh:73-79; e2e (stub), step "The
             agent's Kubernetes and systemd recipes"
  Shown by:  `gh run view 44881325932 --log-failed`: "FAIL: the agent image
             is not on the kind node" 1.5 s after `kind load image-archive`
             returned 0. PR run 44880245200 on the same tree, same runner
             image (ubuntu-26.04 20261116.202.1), kind v0.33.0 and
             kindest/node v1.37.0 printed the image
             ("docker.io/library/culprit-agent ci 09c259fcdc3a7 5.84MB").
             `gh run rerun 44881325932 --failed`: attempt 2 green on every
             job, gate and narration-parity included. Earlier attempt-1
             failures over 100 runs were other causes (44522173729: apt
             mirror; 44597852296: the Q42 HOSTNAME record, since fixed). The
             guard on line 79 did its job: without it the pod would have
             sat in ImagePullBackOff (run 42804120023). Logs in
             ../audit-44/logs/run-4488*.
  Proposed:  not a retry (§2). On that failure, print what would attribute
             it next time: `kind version`, `docker exec … ctr -n k8s.io
             images ls`, the archive's index.json and the import's own
             output. A mutation: delete the import, see the guard fire.
  Risk:      none; diagnostics only.
  Needs:     the architecture session: whether a first-occurrence infra
             flake with a working guard is accepted as is.

F44-008  On a push to main, images publish without waiting for the
         end-to-end checks
  Area:      backend (CI ordering)
  Severity:  S2
  Evidence:  VERIFIED (static needs: lists; run timings read)
  Where:     .github/workflows/ci-cd.yml:801-827; images.yml:210-310
  Shown by:  `build` needs test, migration-round-trip and cli only. On run
             44881325932 every publish job pushed :sha and :latest while
             e2e (stub) failed and gate went red. Detail: 4.3-backend.md B-03.
  Proposed:  publish in a job that needs `gate`, with the built images
             passed as artifacts on push and tag; a test_ci_workflow.py
             assertion "publish needs gate" fails first. Cost: about 40 s on
             main and tags only; pull requests unchanged. (Making build need
             every check instead would add about 2.5 min to every run.)
  Risk:      artifact size and retention; the release workflow's verify
             step must still find what it attests.
  Needs:     the architecture session (ruleset and release path).

F44-009  `just quickstart` over an env file from before Phase 35 dies in a
         migration with a Python traceback
  Area:      reliability, readiness
  Severity:  S2
  Evidence:  VERIFIED (on this machine)
  Where:     justfile:435-440 (backfills INVENTORY_DB_PASSWORD only);
             api/migrations/versions/a6c2e9d4f8b1_narrations.py:71,145
  Shown by:  `just quickstart` (../audit-44/logs/quickstart.log): "==>
             infra/.env.prod already exists, reusing it" … "RuntimeError:
             NARRATOR_DB_PASSWORD must be set in the environment to run this
             migration", exit 1, a 30-line traceback. UPGRADING.md:215 names
             the key for a real install; the quickstart path does not.
  Proposed:  backfill every generated key bootstrap_env.py knows, as the
             recipe already does for one; or fail before migrating, naming
             the key and the fix. Test first: a script test running the
             recipe's check over an env file without the key.
  Risk:      none; generated passwords for roles that do not exist yet.
  Needs:     nothing.

F44-010  The migration-head reader reports an Alembic merge's parents as
         extra heads
  Area:      core
  Severity:  S2 (a wrong INTENT fact)
  Evidence:  VERIFIED
  Where:     cli/internal/extract/config_keys.go:396-399 (down_revision must
             start with a quote), :300-313
  Shown by:  ../audit-44/edges/c09: a1 <- b2, a1 <- c3, d4 merges ("b2",
             "c3"). `culprit intent --format json`: component:svc
             migration_head ['b2', 'c3', 'd4']. The only head is d4; against
             a database at d4 that is a false divergence. Detail: 4.2-core.md
             C-09.
  Proposed:  read a tuple down_revision; test first with this fixture.
  Risk:      low; the Python extractor's reader is independent on purpose.
  Needs:     nothing.

F44-011  A value's format class flips on its digits: WORKERS=1 and
         WORKERS=4 are "different kinds of value"
  Area:      core
  Severity:  S2 (a misleading divergence)
  Evidence:  VERIFIED
  Where:     cli/internal/model/shape.go:275-278 (1|0 booleanish; 2-65499
             port; the port pattern stops at 65499)
  Shown by:  two process captures with WORKERS=1 and WORKERS=4, `culprit
             diff`: "[cosmetic] config:api/WORKERS … disagree about
             value_shape: string/port/short vs string/booleanish/short".
             Cosmetic here only because no source reads it; a key that is
             read rises to degrades. SHLVL is classed booleanish. Detail:
             4.2-core.md C-02.
  Proposed:  a shape rule that does not split a counter by value, held by
             the shared shape fixture. Test first: the fixture row.
  Risk:      a shape change moves recorded captures' shapes; verify
             compares like with like only within one version.
  Needs:     the architecture session (what a shape claims).

F44-012  The process adapter captures the invoking shell's own variables
  Area:      core (determinism)
  Severity:  S2
  Evidence:  VERIFIED that they are captured; RISK that verify then says
             changed_underneath
  Where:     cli/internal/capture/adapters.go:471-493
  Shown by:  `culprit env capture staging --format text` in the tour:
             config:api/SHLVL, config:api/OLDPWD, config:api/_ (and every
             other variable in the shell: 111 keys). diagnose and verify are
             separate invocations, so a different shell or launcher changes
             these between them. Same class as Q42. Detail: 4.2-core.md C-01.
  Proposed:  Q42's ruling forbids a list of names; the architecture
             session decides (a declared key set per component, or the
             manifest's INTENT keys only).
  Risk:      narrowing what is captured narrows what diff can see.
  Needs:     the architecture session.

F44-013  The Kubernetes capture reads the Deployment template only, yet
         marks the environment complete
  Area:      core (honest absence)
  Severity:  S2
  Evidence:  RISK
  Where:     cli/internal/capture/adapters.go:315-378 (Complete: true at 324)
  Shown by:  reading: a key set by the image's ENV, envFrom or a mutating
             webhook is reported missing. Detail: 4.2-core.md C-10.
  Proposed:  mark it incomplete unless every source was read; test first
             with a fixture Deployment using envFrom.
  Risk:      more "not checked" lines on Kubernetes environments.
  Needs:     nothing.

F44-014  An agent task that is claimed and never completed stays claimed
         for ever
  Area:      backend, reliability
  Severity:  S2
  Evidence:  RISK
  Where:     api/app/agents/service.py:263-333
  Shown by:  reading: nothing expires or reclaims a claim; the agent exits
             on any error and skips claimed tasks after a restart. The
             dashboard waits on "Walking the request path…". Detail:
             4.3-backend.md B-01.
  Proposed:  a claim deadline, after which the task is failed with a
             reason; test first in api/tests with a claim and a clock.
  Risk:      a slow walk past the deadline.
  Needs:     the architecture session (the deadline).

F44-015  The sign-in rate limit is one bucket for everyone behind Caddy
  Area:      backend, security
  Severity:  S2
  Evidence:  RISK
  Where:     api/app/incidents/limiter.py:20; infra/docker-compose.prod.yml:64;
             docker-compose.quickstart.yml:69
  Shown by:  reading: get_remote_address with no forwarded-allow-ips sees
             Caddy's address; ten bad sign-ins a minute lock the team out.
             LIMITS says "per address". Detail: 4.3-backend.md B-02.
  Proposed:  trust the proxy's X-Forwarded-For for the one hop; test first.
  Risk:      a spoofed header if the API is ever exposed without Caddy.
  Needs:     nothing.

F44-016  The documented path does not work from PowerShell, and on Windows
         the built binary has no .exe
  Area:      readiness
  Severity:  S2
  Evidence:  VERIFIED (the binary); RISK (a PowerShell user's path)
  Where:     justfile:4 (set shell := bash), :129 (-o bin/culprit);
             README.md:219-229; docs/GUIDE.md:269-271, :885-893
  Shown by:  `just cli-build` here wrote cli/bin/culprit, "PE32+ executable
             for MS Windows", with no extension, beside a stale culprit.exe
             from 12 November. PowerShell and an MCP client launching
             "culprit" look for culprit.exe (PATHEXT) and find the stale one
             or none. No document says Windows needs Git Bash. Detail:
             4.7-4.9 D-02.
  Proposed:  name the output with go env GOEXE; state Git Bash as a Windows
             prerequisite. Test first: a check that the recipe's output
             name has GOEXE.
  Risk:      scripts that call cli/bin/culprit on Windows.
  Needs:     nothing.

F44-017  Restore has never been tested, and the documented restore may fail
         or lose tables
  Area:      readiness, reliability
  Severity:  S2
  Evidence:  VERIFIED (no test or run restores; the documented command uses
             variables nothing sets); RISK (table loss)
  Where:     scripts/backup.sh; docs/UPGRADING.md:327-353
  Shown by:  4.7-4.9 D-09.
  Proposed:  a restore round trip in CI over the migration-round-trip
             database. Test first: that job, red on today's instructions.
  Risk:      CI time.
  Needs:     nothing.

F44-018  Nothing fails a CI run because nothing was checked
  Area:      core, readiness
  Severity:  S2
  Evidence:  VERIFIED
  Where:     cli/cmd/culprit/check.go:121-136; probe.go:115-127
  Shown by:  `culprit check` in ../audit-44/edges/empty: "No divergences. 0
             fact(s) compared across 0 subject(s)", exit 0. A diff against an
             environment the compose adapter could not see: "No
             divergences", exit 0 (it lists the gap). Detail: 4.7-4.9 D-11.
  Proposed:  a --fail-on-unchecked (or a non-zero exit when nothing was
             compared); test first.
  Risk:      a new flag; no default changes.
  Needs:     the architecture session (exit code meaning, F44-035).

F44-019  There is no field-trial runbook, and no way to record that a
         finding on a real system was confirmed
  Area:      readiness
  Severity:  S2
  Evidence:  VERIFIED (none exists)
  Where:     docs/; api/app/verifications; README.md:198
  Shown by:  the draft is in ../audit-44/notes/4.7-4.9-docs-cli-tests.md
             ("Field-trial runbook — draft"). What it must contain: Culprit
             in development and CI mode only, against a project the owner
             does not control; check, intent, env capture of a local
             process environment only, with --no-import (F44-003) and every
             output and state directory outside the project; nothing
             written to it (verify with git status in the clone after every
             step); the clone pinned to a commit; how a finding is
             confirmed (by reading the target's code and, where it can be,
             by the project's own maintainers) and recorded (the subject,
             both sources with their lines, the Culprit commit and the
             target commit, confirmed or false positive, and why).
  Proposed:  write the runbook in §7 as planned; add a way to record a
             confirmed or false-positive check finding.
  Risk:      none.
  Needs:     the owner (where findings are recorded; disclosure to the
             target project).

F44-020  WITHDRAWN: an unreachable database is NOT reported as "not granted"
  Area:      interface
  Severity:  none (withdrawn)
  Evidence:  NOT REPRODUCED by phase-auditor, and not by this run on a
             second look
  Where:     —
  Shown by:  the first run's grep joined two sections: the "Refused (1)"
             heading belonged to the config-values refusal, and the line
             below it ("api's database was not read: the database could not
             be reached") is listed under "Not checked — gaps", which is
             right. Rerun: `culprit env capture prod -f dbenv.yaml --format
             text` with the DSN at 127.0.0.1:1 and unparseable: both under
             "Not checked". Kept so the number is not reused.
  Proposed:  nothing.
  Needs:     nothing.

F44-021  `--change action:<words>` is redacted by the API but not by the CLI
  Area:      security
  Severity:  S2
  Evidence:  RISK (not reproduced: the only local investigation had no
             readings, F44-091)
  Where:     cli/cmd/culprit/verify.go; api/app/verifications
  Shown by:  4.4-security.md S-06, R-06.
  Proposed:  redact in the shared change parser. Test first.
  Risk:      none.
  Needs:     nothing.

F44-022  Some 422 bodies quote the refused value in msg
  Area:      security, backend
  Severity:  S2
  Evidence:  RISK
  Where:     api/app/investigations.py:39; subjects.py:151;
             agents/schemas.py parse_change
  Shown by:  4.4-security.md S-07, R-07 (needs the API: not run).
  Proposed:  validators name the field, not the value; test first with a
             DSN as a subject.
  Risk:      LIMITS' 422 entry changes.
  Needs:     nothing.

F44-023  Text from the diagnosed system reaches the narrator and MCP agents
         with no data framing
  Area:      security
  Severity:  S2
  Evidence:  RISK
  Where:     worker/app/narrate (prompt); cli/internal/mcp results
  Shown by:  4.4-security.md S-08. The narrator's output is checked against
             the investigation before it is stored, which bounds the harm;
             an MCP agent's is not.
  Proposed:  fence system-supplied strings as data in both, with a test that
             an instruction inside a reason is rendered as data.
  Risk:      narration wording.
  Needs:     the architecture session.
```

#### S3

```
F44-024  Two isolation mutations survive every test
  Area:      tests, core
  Severity:  S3
  Evidence:  VERIFIED
  Where:     cli/internal/isolate/isolate.go (Walk.fails, ruleOutBelow)
  Shown by:  ../audit-44/scripts/mutate.py, each restored by git checkout
             (tree clean after). Killed: V1-V5 (the verdict rules,
             model/verification.go), SEV1-2 (severity), CAP1-2 (the
             allowlist and its refusal). V2's first form only failed to
             compile and was rerun valid (killed). Survived: ISO1 (a pass no
             longer rules out the components below it) and ISO2
             (ruleOutBelow stops at the component), against
             ./internal/isolate/... and ./cmd/culprit/... .
             ../audit-44/logs/mutations.log.
  Proposed:  a walk test where a passing component has an open hypothesis
             below it; it must be ruled out, citing the reading.
  Risk:      none.
  Needs:     nothing.

F44-025  Legacy: incidents
  Area:      legacy
  Severity:  S3
  Evidence:  VERIFIED (static); "always empty" RISK
  Where:     api/app/incidents/router.py:40,52; frontend/src/routes/
             AppRoutes.tsx:61-63; infra/deploy.sh (health check)
  Shown by:  nothing writes the tables (insert grants revoked); still in the
             navigation as history; deploy's health check calls
             /api/incidents. Detail: 4.1-map.md M-01.
  Proposed:  nothing removed; the owner decides. If kept, deploy's health
             check moves to /health.
  Risk:      —
  Needs:     the owner.

F44-026  Legacy: postmortems are live, writable and tied only to incidents
  Area:      legacy
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     api/app/postmortems/router.py:65-124; AppRoutes.tsx:63,66-68
  Shown by:  a postmortem can link only to an incident, never to an
             investigation; it is in the navigation without a history mark.
             Detail: 4.1-map.md M-02.
  Proposed:  the owner decides: mark as history, or link to investigations.
  Needs:     the owner.

F44-027  Legacy: RAG memory is written only by this repository's own hooks
         and read only by the Python MCP server
  Area:      legacy
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     api/app/memory/router.py:84-234 (mounted without router-level
             auth, main.py:305); worker/app/rag
  Shown by:  worker retrieval used only by tests; mcp_server is in no
             compose file. Detail: 4.1-map.md M-03.
  Needs:     the owner (and the router's auth reviewed in the batch).

F44-028  Legacy: anomaly detection writes two outputs nothing reads
  Area:      legacy
  Severity:  S3
  Evidence:  VERIFIED (static); the load RISK
  Where:     worker/app/anomaly/job.py:62-66,412,422; worker/app/main.py:150
  Shown by:  anomalies reachable only through frozen incident joins;
             impedance readings have no read path; the binary's impedance
             probe has no metrics source. Detail: 4.1-map.md M-04.
  Needs:     the owner.

F44-029  Legacy: the ingest gateway and Redis Streams feed scoring nothing
         reads; ingested logs are never read
  Area:      legacy
  Severity:  S4
  Evidence:  VERIFIED (static)
  Where:     api/app/ingest_gateway/main.py:157-196, streams.py:9-27
  Shown by:  4.1-map.md M-05; a quickstart compose comment still promises
             "an incident within ~5 minutes".
  Needs:     the owner.

F44-030  INSTALL.md onboards services onto the telemetry path and never
         reaches the diagnostic journey
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED
  Where:     docs/INSTALL.md:135-146
  Shown by:  no mention of the agent, the project token or diagnose.
             Detail: 4.1-map.md M-06.
  Proposed:  an "after install" section that ends in a diagnosis.

F44-031  README "Status" is stale
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED
  Where:     README.md:244-261
  Shown by:  Phase 40 "in progress", 41-43 "planned". Detail: M-07, D-01.

F44-032  The root help is stale, and there is no version subcommand
  Area:      interface
  Severity:  S4
  Evidence:  VERIFIED
  Where:     cli/cmd/culprit/main.go:96-105
  Shown by:  `culprit --help`: "This build implements the INTENT plane …
             the OBSERVED plane (culprit probe). See docs/DIAGNOSTIC_PLAN.md";
             diagnose, verify, agent and mcp absent from the prose. `culprit
             version`: "unknown command"; `culprit --version` works.
             Detail: M-09.

F44-033  Two flags' help is garbled by pflag's backtick convention
  Area:      interface
  Severity:  S4
  Evidence:  VERIFIED
  Where:     cli/cmd/culprit/env.go (--sign-key), diagnose.go (--state-dir)
  Shown by:  `culprit env capture --help`: "--sign-key openssl genpkey
             -algorithm ed25519   sign the envelope with…"; `culprit diagnose
             --help`: "--state-dir culprit verify   where to keep…". pflag
             takes the first backticked text in a usage string as the
             value's name.
  Proposed:  no backticks in usage strings, or a lint over every flag.

F44-034  `culprit probe -f` does not search upward for culprit.yaml
  Area:      interface
  Severity:  S4
  Evidence:  VERIFIED (static)
  Where:     cli/cmd/culprit/probe.go:132
  Shown by:  default "culprit.yaml" vs every other command's upward search.
             Detail: M-10, D-13.

F44-035  Exit codes mean different things per command, and half the help
         texts do not state them
  Area:      interface
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     cli/cmd/culprit/*.go Long texts; docs/PROBES.md:557-565
  Shown by:  check: 0 clean, 1 findings, 2 could not run; diagnose: 0
             complete, 1 partial; env capture with nothing seen: 0. Table in
             4.7-4.9 D-12; M-11.
  Needs:     the architecture session (one convention).

F44-036  Two MCP servers are both named "culprit"
  Area:      interface
  Severity:  S4
  Evidence:  VERIFIED
  Where:     .mcp.json; docs/GUIDE.md:885-893
  Shown by:  M-08.

F44-037  This plan's §4.1 names `init`, `capture` and `pair` as top-level
         commands
  Area:      readiness (the brief)
  Severity:  S4
  Evidence:  VERIFIED (`culprit --help` lists agent, check, diagnose, diff,
             env, intent, mcp, probe, verify)
  Where:     docs/FIELD_READINESS_PLAN.md:212-213
  Shown by:  they are `agent init`, `env capture`, `agent pair`. M-12.
  Needs:     the architecture session (the plan's text).

F44-038  The worker says link_recent_changes "reads only"; it inserts
  Area:      legacy
  Severity:  S4
  Evidence:  VERIFIED (static)
  Where:     worker/app/main.py:151-154; worker/app/memory/link_job.py:30-31,95-162
  Shown by:  M-13: every 5 s, into incident_change_links, over tables nothing
             writes.
  Needs:     the owner (with F44-025).

F44-039  A telemetry entry Postgres refuses wedges its stream's drain
  Area:      backend, reliability
  Severity:  S3
  Evidence:  RISK
  Where:     worker/app/consumer.py:199-230, :91-97, :296-302
  Shown by:  B-04 (e.g. a NUL byte); logs stall behind metrics.
  Proposed:  dead-letter the entry; test first with a refused row.

F44-040  The drain lock can be released by another holder and expires under
         a slow write
  Area:      backend, reliability
  Severity:  S3
  Evidence:  RISK
  Where:     worker/app/consumer.py:287-313, :325-343
  Shown by:  B-05: unconditional delete, 30 s expiry: overlapping drains
             duplicate rows.
  Proposed:  compare-and-delete with a token.

F44-041  "Planted or real, never both" is a check-then-insert
  Area:      backend
  Severity:  S3
  Evidence:  RISK
  Where:     api/app/verifications/router.py:84-96; service.py:130-139,164-191
  Shown by:  B-06: two concurrent verifications can store both labels.
  Proposed:  a constraint, in a new migration; test first with two sessions.

F44-042  Demote, disable or a password reset does not end a session at once,
         and LIMITS does not say so
  Area:      backend, security
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     api/app/auth/dependencies.py:29-62; router.py:96-122;
             users_router.py:209-221
  Shown by:  B-07: up to 30 s for demote/disable; existing tokens work for up
             to 60 min after a password reset.
  Proposed:  a LIMITS entry now; a token version later.

F44-043  No body-size cap on /api/*; a signed route reads the whole body
         before authenticating
  Area:      backend, security
  Severity:  S3
  Evidence:  RISK
  Where:     frontend/Caddyfile:23-25; api/app/agents/dependencies.py:85-123,171-184
  Shown by:  B-08.
  Proposed:  a request_body max_size in Caddy and a check in the dependency.

F44-044  The API's error envelope has four shapes; the dashboard shows the
         raw JSON
  Area:      backend, interface
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     api/app/main.py:226; errors.py:70; agents/router.py:121;
             frontend/src/lib/api.ts:77-95
  Shown by:  B-09.

F44-045  Three paths around the boundary checks
  Area:      backend (boundaries)
  Severity:  S3
  Evidence:  VERIFIED (static); the bypasses RISK
  Where:     cli/cmd/culprit/check_test.go:266-269; worker/pyproject.toml
  Shown by:  B-10: the network allowlist lists only internal/..., so
             cmd/culprit is unchecked; it skips rather than fails when go
             list errors; the worker's provider contract omits urllib,
             http.client, voyageai, google and app.main.
  Proposed:  each made a failing case first (a mutation per gap).

F44-046  LIMITS says the agent has no transport to the control plane
  Area:      readiness (docs)
  Severity:  S3
  Evidence:  VERIFIED
  Where:     docs/LIMITS.md:1951-1957
  Shown by:  B-11; Phase 33 built it.

F44-051  SOURCE_DATE_EPOCH pins every clock, not only intent's
  Area:      core (determinism)
  Severity:  S3
  Evidence:  RISK
  Where:     cli/cmd/culprit/main.go:218-225; callers in check.go:84,111
  Shown by:  C-03: suppression expiry, investigation times, the TLS
             certificate class; before and after captures share an id.

F44-055  DNS, port and TLS observations are CONFIGURED facts that verify
         counts as change
  Area:      core
  Severity:  S3
  Evidence:  RISK
  Where:     cli/internal/capture/capture.go:556-600; network.go:40-62;
             verify/verify.go:274
  Shown by:  C-07: a transient blip during verify is an unexplained change.
  Needs:     the architecture session (which plane they belong to).

F44-057  Unreadable or too-deep parts of a repository are skipped with no
         record
  Area:      core (honest absence)
  Severity:  S3
  Evidence:  RISK
  Where:     cli/internal/extract/artefacts.go:88-111; the Node and Python
             extractors
  Shown by:  C-11.
  Proposed:  a skipped entry naming the path; test first with an unreadable
             directory.

F44-058  A migration file that does not parse is dropped, and the chain can
         still look linear
  Area:      core
  Severity:  S3
  Evidence:  RISK
  Where:     extractors/python/culprit_extract_python/migrations.py:76-77,153-157
  Shown by:  C-12: false "column not migrated" findings.

F44-063  Severity treats an edge with no criticality as background, unlike
         its own doc and graph.py
  Area:      core, parity
  Severity:  S3
  Evidence:  RISK (the code difference is static)
  Where:     cli/internal/severity/severity.go:116-128 (doc at :20-26)
  Shown by:  C-17.
  Needs:     the architecture session (which is right).

F44-064  Three values are computed in Go and Python with no shared fixture
  Area:      core (parity)
  Severity:  S3
  Evidence:  VERIFIED (static: no fixture names them; every other
             shared/tests fixture is read by both suites)
  Where:     (a) the snapshot diff: shared/culprit_model/capture_diff.py:120
             vs cli/internal/verify/verify.go:274; (b) never-render-a-value:
             render_value vs report.go:379 renderValue; (c) the request path:
             graph.py upstream_connections vs severity.go BuildGraph (which
             already disagree, F44-063)
  Shown by:  C-18.
  Proposed:  one fixture each under shared/tests.

F44-065  Four gates have no test that shows them red
  Area:      tests
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     scripts/check_schema_drift.py, check_migration_round_trip.py,
             check_agent_image.sh, fast_gates.sh
  Shown by:  C-19.
  Proposed:  a mutation test each.

F44-067  The GUIDE's tour keeps the state directory inside the project
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     docs/GUIDE.md:517,536,621,670 (--state-dir ./state); verify.go:53
  Shown by:  D-04: the code says that must never happen.

F44-068  Nothing says what Culprit leaves on a machine, or how to remove it
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED
  Where:     justfile:704-707; the state directory (default
             %LOCALAPPDATA%\culprit, shown by `culprit diagnose --help`)
  Shown by:  D-05: state dir, volumes, images, infra/.env.prod with the
             admin password in clear.

F44-069  Version reporting: every local build is 0.1.0, no commit, and the
         control plane reports no version
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED (`culprit --version`: "culprit version 0.1.0")
  Where:     VERSION; justfile:129
  Shown by:  D-06.

F44-070  What is safe to attach to a bug report is stated for a capture only
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     CONTRIBUTING.md:8-10; SECURITY.md; docs/PERMISSIONS.md:644
  Shown by:  D-07; and `culprit intent` output is not safe (F44-001).

F44-071  Control-plane logging is undocumented, and container logs are
         unbounded
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     api/app/main.py:262-280; the compose files (no logging options)
  Shown by:  D-08.

F44-072  Backup documentation is stale, and INSTALL's upgrade skips the
         backup
  Area:      readiness
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     docs/UPGRADING.md:312-322; INSTALL.md:139-145; infra/deploy.sh
  Shown by:  D-10: the table list is from the incident era.

F44-074  Errors send users to repository paths and plan jargon; there is no
         culprit.yaml reference
  Area:      interface
  Severity:  S3
  Evidence:  VERIFIED
  Where:     cli/cmd/culprit/main.go:259-262; capability.go:168
  Shown by:  with no manifest: "culprit: no culprit.yaml found here or in any
             parent directory. Create one describing your components, or
             pass -f. See docs/EXTRACTOR_PROTOCOL.md" (an extractor author's
             document, not a manifest reference). D-15.

F44-075  `culprit mcp` answers are unbounded and each is sent twice
  Area:      interface
  Severity:  S3
  Evidence:  VERIFIED
  Where:     cli/internal/mcp/mcp.go:102-110
  Shown by:  ../audit-44/scripts/mcp_session.py: culprit_system_model on a
             two-component manifest returned 19,516 bytes, the document as
             content text and again as structuredContent. D-16.
  Proposed:  one copy, and a bound with a truncation notice.

F44-077  The Python MCP server's culprit_coupled_files answers from
         Culprit's own repository file
  Area:      legacy
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     mcp_server/config.py:31; tools.py:399-432
  Shown by:  D-18.
  Needs:     the owner (with F44-027).

F44-081  The documented paths have no end-to-end test; some e2e route tests
         assert only that the page rendered
  Area:      tests
  Severity:  S3
  Evidence:  VERIFIED (static)
  Where:     .github/workflows; frontend/e2e/tour.spec.ts:58-61,137-142
  Shown by:  D-22: no CI run of the GUIDE tour, install.sh, backup and
             restore, a third-party repository, or Windows.

F44-083  culprit.yaml can run any command, and the docs say otherwise
  Area:      security
  Severity:  S3
  Evidence:  VERIFIED (static); with F44-003 shown
  Where:     an extractor's command (any argv, run by default);
             EXTRACTOR_PROTOCOL.md §7; MCP culprit_check's description
  Shown by:  S-09: "Reads files only". docker and kubectl arguments have no
             "--" before positional names.
  Proposed:  say it: a culprit.yaml is code, as a Makefile is.

F44-084  CLI errors echo raw input
  Area:      security
  Severity:  S3
  Evidence:  RISK
  Where:     e.g. "--input %q", "%q is not a URL" (cli/cmd/culprit/probe.go)
  Shown by:  S-10.

F44-085  `just up` publishes Postgres, Redis, Grafana and Tempo on every
         interface, with known credentials
  Area:      security
  Severity:  S3
  Evidence:  VERIFIED (static); RISK (reachability)
  Where:     infra/docker-compose.yml
  Shown by:  S-11.
  Proposed:  bind to 127.0.0.1.

F44-086  Nothing refuses a placeholder JWT_SECRET_KEY at start-up
  Area:      security
  Severity:  S3
  Evidence:  RISK
  Where:     api/app (settings)
  Shown by:  S-12.

F44-087  One secret-scanning alert is open, and /ci does not gate on secret
         scanning
  Area:      security
  Severity:  S3
  Evidence:  VERIFIED (read through gh api; nothing dismissed)
  Where:     alert #1, stripe_api_key, a planted fixture at
             cli/internal/capture/capture_test.go:31
  Shown by:  S-13. Code-scanning and Dependabot: 0 open.
  Needs:     the owner (dismissing an alert).

F44-091  `verify` on an investigation with no readings fails with an
         internal-sounding message
  Area:      interface
  Severity:  S3
  Evidence:  VERIFIED
  Where:     cli/cmd/culprit/verify.go
  Shown by:  `culprit verify inv-49e9046ba15924f9 … --change action:…`:
             "culprit: the verification does not validate: verification
             ver-… re-runs nothing", exit 2. It should say there was nothing
             to re-measure and why.
```

#### S4

```
F44-047  No write is idempotent by key; two concurrent create-user calls
         answer 500, not 409
  Area: backend · Severity: S4 · Evidence: RISK · Where: api/app/auth/users_router.py ·
  Shown by: 4.3-backend.md B-12 · Proposed: catch the unique violation as 409.

F44-048  The OpenAPI schema and Swagger UI are served without
         authentication
  Area: security · Severity: S4 · Evidence: VERIFIED (static) · Where: api/app/main.py ·
  Shown by: B-13 · Needs: the owner (a public schema may be intended).

F44-049  The audit-log route is unbounded, and the investigations list sorts
         on unindexed columns
  Area: performance · Severity: S4 · Evidence: VERIFIED (static) · Where: B-14 ·
  Shown by: small at trial scale.

F44-050  CORS origins are split on "," without trimming
  Area: backend · Severity: S4 · Evidence: VERIFIED (static) · Where: api/app/main.py (B-15).

F44-052  capture_id hashes the absolute manifest path
  Area: core · Severity: S4 · Evidence: VERIFIED (static) ·
  Where: cli/internal/extract/orchestrator.go:310-324; capture.go:691 ·
  Shown by: C-04: the same tree in two clones (or Windows and Linux) has
  different ids. intent and check run twice here were identical once ids and
  times were removed (../audit-44/scripts/canon.py).

F44-053  Manifest validation reports the first invalid entry in map order
  Area: core · Severity: S4 · Evidence: RISK · Where: cli/internal/extract/environments.go:254,337,349 (C-05).

F44-054  A latency reading's budget is found by ranging over a map
  Area: core · Severity: S4 · Evidence: RISK · Where: verify/verify.go:260-267;
  isolate/isolate.go:1108-1116 (C-06).

F44-056  The Python extractor puts absolute paths in skip reasons
  Area: core · Severity: S4 · Evidence: VERIFIED (the tour's output names
  C:\Users\… paths) · Where: extractors/python/culprit_extract_python/cli.py:285,358-364 (C-08).

F44-059  One non-UTF-8 .py file skips a whole want in the Python extractor
  Area: core · Severity: S4 · Evidence: RISK · Where: static_scan.py:90-91,247-248 (C-13).

F44-060  The adapters handle invalid variable names differently; LIMITS says
         all drop them
  Area: core · Severity: S4 · Evidence: VERIFIED (static) · Where: adapters.go:561-564,596-599 (C-14).

F44-061  Image-digest errors are swallowed; packages without a version
         vanish without a skip
  Area: core · Severity: S4 · Evidence: RISK · Where: adapters.go:206-211,400-418 (C-15).

F44-062  The --no-plugins skip names no component
  Area: interface · Severity: S4 · Evidence: VERIFIED (static) · Where: orchestrator.go:175-183 (C-16).

F44-066  Two doc comments name what the code does not do
  Area: core · Severity: S4 · Evidence: VERIFIED (static) · Where: model/shape.go:184
  (a fixture that does not exist); dbsession/session.go:41 (C-20).

F44-073  No help examples outside probe; probe's target list omits http:
         subjects
  Area: interface · Severity: S4 · Evidence: VERIFIED (static) · Where: cli/cmd/culprit/*.go (D-14).

F44-076  GUIDE says MCP answers "carry no prose"; they carry fixed sentences
  Area: interface · Severity: S4 · Evidence: VERIFIED · Where: docs/GUIDE.md:915 (D-17) ·
  Shown by: the MCP session's answers; facts and narration are still apart.

F44-078  Tour traps: `culprit verify <id>` is a redirect in bash, and the
         tour's manifest is not the captures'
  Area: readiness · Severity: S4 · Evidence: VERIFIED (static) · Where: GUIDE.md:388,536,670 (D-19).

F44-079  README captures are not re-rendered by CI
  Area: readiness · Severity: S4 · Evidence: RISK · Where: scripts/render_captures.py (D-20).

F44-080  `just --list` shows only the last comment line of each recipe
  Area: interface · Severity: S4 · Evidence: RISK · Where: justfile:202-203,243-244 (D-21).

F44-082  cli/internal/render has no test
  Area: tests · Severity: S4 · Evidence: VERIFIED · Where: cli/internal/render ·
  Shown by: `go test -cover ./...`: "render coverage: 0.0% of statements" (F44-001 lives there).

F44-088  The frontend image runs Caddy as root
  Area: security · Severity: S4 · Evidence: VERIFIED (static) · Where: frontend/Dockerfile:48-56 (S-14).

F44-089  The security-doc checker holds only "cannot" claims, and checks only
         that the named test exists
  Area: tests · Severity: S4 · Evidence: VERIFIED (static) · Where: scripts/check_security_doc.py (S-15).

F44-090  A .env.example key with invalid UTF-8 becomes a subject with U+FFFD
  Area: core · Severity: S4 · Evidence: VERIFIED · Where: the .env.example reader and subjects.build ·
  Shown by: ../audit-44/edges/weird: key bytes FF FE "BADKEY" gave
  config:svc/\ufffd\ufffdBADKEY, a subject no environment can match. Large
  (2 MB), empty, Latin-1 and CRLF values were handled (exists facts, shapes,
  no crash).

F44-092  The quickstart prints the admin password, and pulls an unpinned
         curlimages/curl:latest
  Area: security · Severity: S4 · Evidence: VERIFIED (static) · Where: justfile (quickstart) ·
  Shown by: 4.7-4.9 notes ("also noted").
```

Every number from F44-001 to F44-092 is used once; numbers follow the
order the findings were drafted, so a few S3 and S4 entries sit out of
numeric order in their block.

### Coverage record

| Area | Inspected | Ran |
|---|---|---|
| Step 0 | run 44881325932's failed log and both e2e (stub) job logs; 100 runs' attempt history | `gh run rerun 44881325932 --failed`: attempt 2 green on every job |
| Baseline | — | `just lint`, `typecheck`, `lint-imports`, `check-schema-drift`, `test` (1998 passed, 6 skipped; worker 93; mcp_server 21; extractors 39), `check_coupled_files.py`, `cli-test` (18 packages), `cli-build`, `culprit check --fail-on=breaks_request_path`, `LLM_PROVIDER=none culprit check`: all exit 0 |
| 4.1 map | every subcommand, API package, worker job, MCP tool (both servers), route, extractor, recipe and workflow job (inventory tables in notes/4.1-map.md); the five legacy surfaces | `culprit --help` and each subcommand's help; MCP tools/list |
| 4.2 core | determinism sources, the parity table, every adapter and extractor for honest absence, the gates (notes/4.2-core.md) | intent, check and check --format sarif twice each, canonicalised: identical. 13 mutations (11 kinds), restored. Honest absence: compose with no project and with no docker, diff against the unseen side. Not run: the journeys through the demo stack, the agent and MCP against the stack (CI's fault library and e2e run them: run 44881325932 attempt 2, fault-library 1-4 and e2e green) |
| 4.3 backend | api, database roles (agent, verification, narrator against PERMISSIONS.md; not all 19), worker, agent and transport, boundaries, CI ordering (notes/4.3-backend.md) | nothing (read only) |
| 4.4 security | redaction, every exit, injection, secrets in the tree, SECURITY.md against its tests, Dockerfiles, alerts through gh api (notes/4.4-security.md) | secrets through capture, text capture, diff, diagnose (text, json, state dir), probe, MCP: no leak. Four malformed and unreachable DSNs: no leak. The extractor-stderr leak (F44-001) and the pattern (F44-002) reproduced. Not run: a full git log -p sweep, Trivy, the API-side recipes |
| 4.5 reliability | — | no manifest, empty repo, invalid kind, version 2, broken YAML, non-UTF-8 / 2 MB / empty / CRLF values, NO_COLOR and a pipe (no ANSI at all), docker absent, compose project absent, unreachable and unparseable DSNs, verify with no readings. Not run: kubectl denied, mid-capture exit, clock skew, interrupted verify, concurrent requests, a control-plane restart (need the stack) |
| 4.6 performance | — | `culprit --version` n=20: min 50, median 56, max 95 ms. `culprit check` on this repository n=5: min 7.0, median 7.3, max 9.0 s. Binary 13,963,776 bytes (Windows, -s -w). Dashboard build: index JS 478.81 kB (147.52 kB gzip), CSS 64.23 kB (23.68 kB gzip): about 171 kB first load against the 200,000-byte budget, which `culprit check` passes. Not measured: capture and walk time against environment size, API latency, the statement and N+1 probes on Culprit's own API (need the stack) |
| 4.7 interface | the CLI's help and errors, MCP answers (notes/4.7-4.9) | the MCP session; the CLI cases above. **The dashboard was not rendered: UNTESTED.** The quickstart failed here (F44-009), and the screenshot script, which signs in with the quickstart's admin account, was refused by this session's permission classifier (it reads infra/.env.prod). No screenshot was taken |
| 4.8 tests | test inventory; e2e assertions (notes/4.7-4.9) | `go test -cover ./...`: cmd/culprit 73.3, agent 42.1, agentauth 82.8, capability 77.6, capture 74.0, dbsession 11.7, check 68.8, diverge 42.7, extract 80.3, isolate 86.7, mcp 81.8, model 77.9, probe 80.2, guardedhttp 8.8, report 52.2, severity 71.3, transport 29.3, verify 84.2, render 0.0, boundarytest 0.0 (each package's own tests only). Python coverage: not measured |
| 4.9 readiness | INSTALL, README, GUIDE, backup, what is written where | the GUIDE tour steps 0-2 on Windows (Git Bash): check, two captures, diff, as documented; output as the GUIDE describes. Not run: install.sh, the Linux fresh clone, steps 3 onward |

### Proposed batches, in order

1. **S1 and security** (one area): F44-001, -002, -003, -004, -005, -006,
   -021, -022, then -083, -084. The redaction fixture first; it holds
   both languages.
2. **Correctness of facts**: F44-010, -011, -012 (after the ruling),
   -013, -057, -058, -063, -064, -090.
3. **Reliability and the backend**: F44-009, -014, -015, -039, -040,
   -041, -042, -043, -044, -047, -050, and F44-008 with the ruleset.
4. **Tests and gates**: F44-024, -045, -065, -082, -089, and F44-007's
   diagnostics.
5. **The interface**: the dashboard audit not done here (4.7) first, then
   F44-018, -032, -033, -034, -035, -074, -075, -091, -073, -076.
6. **Documentation and the first run**: F44-016, -017, -019 (the
   runbook), -030, -031, -046, -067 to -072, -078 to -081, -037.
7. **Legacy**: F44-025 to -029, -038, -077, after the owner's decision.

### Questions for the owner

1. **Code execution on the target (F44-003).** May the field trial import
   the target's Python (runtime introspection), or does it run
   `--no-import` only?
2. **Legacy surfaces (F44-025 to -029, -038, -077).** Keep, mark as
   history, or retire: incidents, postmortems, RAG memory and the Python
   MCP server, anomaly detection, the ingest gateway.
3. **Secret-scanning alert #1 (F44-087).** Dismiss it as a test fixture,
   and should `/ci` gate on secret scanning?
4. **The dashboard audit (4.7).** Allow the screenshot run to sign in with
   the quickstart's admin account (it reads `infra/.env.prod`), or brief
   another way to render the routes; and regenerate or patch this
   machine's `infra/.env.prod` (F44-009).
5. **Publishing (F44-008).** Should `main`'s publish wait for `gate`, at
   about 40 s on `main` and tags?
6. **Where a confirmed field finding is recorded, and disclosure to the
   target project (F44-019).**

---

## §6. Batches (written by the reviews)

The review that rules on each batch writes that batch's brief here.

### Review of part 1 — the audit, merged as `6f64f69` (PR #71), 2026-11-23

**Accepted.** The register is sound: every S1 reproduced here, and the audit
says plainly what it could not reach. The batches below are the plan; the
owner's two questions are put to him and do not block batch 1.

**CI.** Read by id from GitHub's API:
- 44887167519 on `3f171f1` (the merge result) and 44888134489 on the report,
  `210d107`: success on every job; `publish` and `deploy` skipped, as on every
  pull request.
- `main`'s push run 45125493937 on `6f64f69`: success on every job (25;
  `deploy` skipped), `narration-parity` and `gate` included.
- **Step 0.** 44881325932's red `e2e (stub)` was kind's image import ending
  without error but leaving nothing on the node (attributed from the log by
  Claude Code); attempt 2 is green on every job. Accepted as F44-007:
  diagnostics on that path, not a retry.
- **Every commit is Verified:** `95e1e77`, `3f171f1`, `210d107` and the merge
  `6f64f69`.

**Reproduced here,** with a binary built from `6f64f69` (Go 1.27.0) and the
inputs in `../audit-44/`, each password planted by the test:
- **F44-001:** `culprit intent`, text and JSON, printed `LeakPw77` and
  `LeakPw88` from an extractor's stderr.
- **F44-002:** the shared pattern redacted 2 of 15 common shapes
  (`DB_PASSWORD=`, `?access_token=`, `Bearer`, `redis://:pw@`, provider
  prefixes and JSON all passed); `culprit check --format sarif` kept
  `DB_PASSWORD=LeakPw88`.
- **F44-003:** `culprit check` with the Python extractor as the GUIDE
  configures it imported a fixture's `config.wsgi` and left three `.pyc` files
  in the project.
- **F44-004:** `probe.auth.token_shape --format json` carried a DSN with its
  password in `measured.audiences`, while the reason line was redacted.
- **F44-005:** read, not run: a probe task's `inputs` are stored in
  `agent_tasks.spec` as given and served back by `GET
  /agents/{id}/tasks/{task}`.
- **F44-006:** `culprit agent --once` wrote `AgentPw66` to its audit log, its
  outbox and its stderr.

**Rulings on the questions for the architecture session:**
- **F44-002, how wide the pattern is.** Two layers, written into `SECURITY.md`
  and LIMITS as the promise. Values Culprit reads as configuration are shown
  only as shapes unless granted (unchanged, structural). Free text that comes
  from outside Culprit is redacted at its one exit by the shared pattern, and
  the pattern's coverage is exactly the fixture's rows. LIMITS names what no
  pattern can catch: a bare secret with no key, scheme or known prefix.
- **F44-003 and the owner's question 1.** Culprit never writes into a project
  it reads. **The field trial runs `--no-import`:** import mode executes the
  project's own code, which on a stranger's project can write, connect or send
  anything. The product's default is unchanged; the docs say plainly what
  import mode does.
- **F44-005, how an agent gets a token.** Secrets never travel through the
  control plane. The probe catalogue declares which inputs carry a secret; the
  task route refuses them, naming the `_env` alternative; the agent reads the
  secret from its own environment (`token_env` already exists).
- **F44-023.** Text from the diagnosed system is data: fenced as quoted data
  in the narrator's prompt, and in MCP results only ever in structured fields.
- **F44-087 and question 3.** Dismiss secret-scanning alert #1 as a test
  fixture, with the evidence; `/ci` reports no run green while a
  secret-scanning or code-scanning alert is open.
- **F44-008 and question 5.** Yes: `main`'s and a tag's publish waits for
  `gate`. About 40 seconds is a fair price for never publishing an image whose
  tests failed. Batch 3.
- **Question 4, the dashboard.** The screens are rendered in CI, not on the
  laptop: a hand-started job on the batch's branch, using the e2e stack's own
  generated admin, uploading the screenshots as an artifact. No local
  credentials, Linux as the reference, nothing for the laptop's memory. Batch
  5's first step. `infra/.env.prod` on the laptop is never regenerated:
  F44-009's fix only adds missing keys (batch 3).
- **F44-012, F44-055 and F44-063** are ruled in batch 2's brief. Batch 1 takes
  F44-012's measurement (decision 8).

**Put to the owner,** not blocking batch 1:
- **The legacy surfaces** (F44-025 to F44-029, F44-038, F44-077): keep, mark
  as history, or retire. Retiring removes code, routes and screens, never
  stored data.
- **Where a confirmed field finding is recorded, and how it is disclosed** to
  the target project (F44-019).

**The batches,** as part 1 proposed them, in this order: 1 security (below); 2
correctness of facts; 3 reliability and the backend, with F44-008 and F44-009;
4 tests and gates, with F44-007's diagnostics; 5 the interface, the
dashboard's screens first; 6 documentation and the first run, with the runbook
(F44-019); 7 legacy, after the owner. F44-020 stays withdrawn. Each review may
move a finding between batches.


### Batch 1 — secrets stay in (brief, 2026-11-23)

**Findings:** F44-001, -002, -003, -004, -005, -006, -021, -022, -023, -082,
-083, -084 and -087. Branch `phase-44-b1`, from `origin/main`; its first
commit is this review.

**Decided:**
1. **Write the promise first.** `SECURITY.md` and LIMITS state the two layers
   above, and what no pattern can catch.
2. **The pattern (F44-002),** widened under one fixture in `shared/tests/`
   that Go and Python both read, its new rows failing first. It covers:
   - a key whose name contains a credential word as one of its parts, in any
     case and after `_`, `-` or `.` (password, passwd, pwd, secret, token,
     apikey or api_key, access_key, private_key, credential, auth), with `=`,
     `:` or JSON quoting;
   - URL userinfo, the password running to the last `@` before the host,
     `:pw@` included, and query parameters with credential-word names;
   - `Authorization` values and `Bearer` and `Basic` credentials, and PEM
     private-key blocks;
   - the provider token prefixes well known enough to be formats: `sk_live_`,
     `sk_test_`, `ghp_`, `gho_`, `ghs_`, `github_pat_`, `glpat-`, Slack's
     `xox` tokens, `AKIA` keys and `AIza` keys.
   - The fixture also has a section of strings that must survive (subjects,
     digests, URLs without credentials) and a section of accepted
     over-redactions, each with a `why`. A subject or a digest is never
     redacted.
3. **Every exit through it, held by one canary test** (F44-001, -004, -006,
   -021, -022, -084). Fix each exit at its one place: render's skip reasons
   (with render's first tests, F44-082); `RedactReading` walking `[]string`,
   with a shared fixture row; the agent's failure reason; `--change action:`;
   422 messages, which name the field and never the value; CLI errors that
   echo input.
   - **The canary:** plant a distinct secret in every input class (an
     extractor's stderr, a probe input and a measured list, an agent task's
     symptom, a change action, a manifest value, a bad CLI argument, a refused
     API body), run every command and route, and assert no planted secret
     appears in stdout, stderr, any file written (reports, SARIF, captures,
     the audit log, the outbox) or any response body. One test in Go and one
     in the API's suite.
   - **Its mutation:** remove one exit's redaction; the canary goes red.
4. **Secrets never travel through the control plane (F44-005).** The probe
   catalogue declares, on the input itself, which inputs carry a secret; the
   catalogue mirror carries the declaration to the API. The task route refuses
   a task that sets one, with a 422 naming the field and its `_env`
   alternative. Tasks stored before this keep what they were given:
   `docs/UPGRADING.md` says so and how to find them; nothing is deleted.
5. **Culprit never writes into the project it reads (F44-003).** Every
   extractor runs with `PYTHONDONTWRITEBYTECODE=1`, and the Python extractor
   sets `sys.dont_write_bytecode` before any import.
   - **Its canary:** snapshot a fixture project's tree (paths, sizes, hashes)
     before and after `intent` and `check` in import mode, and require it
     unchanged. Mutation: drop the variable; the canary goes red.
   - `docs/GUIDE.md`, `docs/EXTRACTOR_PROTOCOL.md` and the MCP tool
     descriptions say plainly that import mode runs the project's code;
     `culprit_check` no longer says it only reads files.
6. **System text is data (F44-023).** In the narrator's prompt, every string
   from the diagnosed system sits inside one fenced block that the
   instructions name as quoted data. In MCP results it appears only in
   structured fields, never inside the fixed sentences, and the tool
   descriptions say those fields are untrusted. Test: a reason holding an
   instruction appears only inside the fence or the field.
   `narration-parity`'s checks do not change.
7. **The rest of the batch.**
   - **F44-083:** the docs say a `culprit.yaml` runs its commands as the user,
     so a manifest is reviewed like code; any MCP tool that can run a manifest
     command says so.
   - **F44-087:** dismiss secret-scanning alert #1 with `gh api` as
     `used_in_tests`, with a one-line evidence comment, and read it back.
     `/ci` reads the open secret-scanning and code-scanning alerts and does
     not report a run green while one is open.
8. **For batch 2, measure only (F44-012):** capture the process environment
   from Git Bash, from PowerShell and inside the demo's order-service
   container; diff the key sets and values; for each key that varies, record
   whether its value equals one the OS reports about the process (hostname,
   working directory, executable path). Change nothing.

**Do NOT:**
- change a verdict rule, the shapes Culprit shows, or `narration-parity`;
- widen a grant, or add a dependency (a secret-scanning library included);
- rewrite or delete a stored task or an audit-log row: append-only stays
  append-only;
- publish, release or deploy anything, or touch the ruleset.

### Review of batch 1 — secrets stay in, merged as `f694cb6` (PR #72), 2026-11-23

**Signed off.** Every S1 from the audit is closed, shown by the architecture
session's own reproductions against the merged binary, and the canaries are
real gates.

**CI.** Read by id from GitHub's API:
- 45169821500 on `ae375e1` (the merge result) and 45171911160 on the report,
  `4fe8935`: success on every job; `publish` and `deploy` skipped, as on every
  pull request.
- 45134071396 and 45137290142 were red on `self-check` only: the README and
  GUIDE quoted 1,753 facts and the tree had 1,754, fixed in `ae375e1`.
  Attributed; not a flake.
- `main`'s push run 45216449983 on `f694cb6`: success on every job (25;
  `deploy` skipped), `narration-parity` and `gate` included.
- **Every commit is Verified,** `14938df` to `4fe8935` and the merge
  `f694cb6`. `14938df`'s tree is exactly the review patch's.

**Verified here,** with a binary built from `f694cb6` (Go 1.27.0):
- **The six S1 reproductions,** rerun with freshly planted values: none of
  them appeared in `intent` text or JSON, `check` text or SARIF (F44-001,
  F44-002), the probe's JSON (F44-004), or the agent's audit log, outbox and
  stderr (F44-006); `check` in import mode left no `.pyc` in the project
  (F44-003).
- **The pattern** caught 12 of the review's 15 shapes. The three misses were
  the review's own malformed strings: `AIza` and `glpat-` keys of their real
  length are caught, and a password with a raw `/` is not a URL (its
  percent-encoded form is caught).
- **Three mutations of its own, each red and restored:** render's skip-reason
  redaction removed, and the agent's reason redaction removed, each turned
  `TestNoPlantedSecretLeavesAnyExit` red; `PYTHONDONTWRITEBYTECODE` dropped
  turned `TestCulpritWritesNothingIntoTheProjectItReads` red, naming both
  `.pyc` files.
- **A nit, carried:** `token_env=NAME` is redacted, though its value names a
  variable, and the fixture records it in neither `survive` nor
  `over_redacted`.

**The run's decisions, accepted:**
- The key stays and only its value goes. The YAML colon form was narrowed when
  a sweep of the repository's own strings found three of Culprit's messages
  mangled; each is now a `survive` row.
- Push protection was respected: the documented Stripe example key was
  replaced with a short fake before anything was pushed. Alert #2, the
  fixture's `AIza` row, was dismissed as used in tests, with the owner's
  approval.
- The README's fact count is CI's, since the local self-check differs in every
  figure.
- Decision 8 measured Git Bash and the order-service image; the PowerShell leg
  was refused by the session's classifier. The measurement is enough to rule
  F44-012.

**The owner's decisions,** given on 2026-11-23:
- **The legacy surfaces are retired** (F44-025 to F44-029, F44-038, F44-077):
  incidents, postmortems, RAG memory with the Python MCP server, anomaly
  detection, and the ingest gateway with Redis Streams. In batch 7, their
  code, routes and screens go; stored data stays, and no table or row is
  deleted without the owner's say. Anything the owner's own Claude Code setup
  relies on is checked first and raised if removing it would break it.
- **Confirmed field findings are private, then disclosed** (F44-019): kept in
  a private record outside the public repository; a security issue goes
  through the target project's private vulnerability reporting or its
  `SECURITY.md` contact, any other bug as a normal issue; nothing is published
  before the project has been told, and never the target's configuration
  values. The runbook says so (batch 6).

**Rulings:**
- **F44-011, what a shape claims.** A format class is lexical: it never
  depends on a number's size. Digits alone are `numeric`; `booleanish` is
  words only; a bare number is never `port`. The vocabulary does not change.
- **F44-012, the launcher's own variables.** Keyed on an OS fact, never a
  name, as Q42 ruled: the working directory joins the hostname, so a variable
  whose value is the directory the OS reports for the process is recorded
  present with its value unshaped. With F44-011, a counter such as `SHLVL`
  keeps one shape. What remains is real: a different launcher is a different
  environment. LIMITS says to launch `diagnose` and `verify` the same way, and
  the tour captures from a clean environment.
- **F44-055, observations are not configuration.** A DNS, port or TLS reading
  is an observation the capture made at one moment. Every CONFIGURED predicate
  declares which it is, where the predicate is defined; `verify` counts
  unexplained changes of configuration only, and reports an observation that
  changed as an observation. No fact changes plane: that would be a schema
  change, and LIMITS records that these observations live in the CONFIGURED
  capture.
- **F44-063, an edge that does not say.** Neither guess is right: following it
  overstates (Python), dropping it understates (Go, against its own doc). A
  component reachable from an entry point only through an edge of `unknown`
  criticality has severity `unknown`, naming that edge, in both languages,
  from one fixture.
- **Q46.** `probe.auth.propagation` takes `token_env`, as
  `probe.auth.token_shape` does, so it can be sent as a task again, under
  F44-005's rule.
- **MCP's `readOnlyHint`.** A tool that can run a manifest's command runs the
  user's code, so its hint is false; it stays true only where a tool runs
  nothing.

### Batch 2 — facts that hold (brief, 2026-11-23)

**Findings:** F44-010, -011, -012, -013, -055, -057, -058, -063, -064 and
-090, Q46, and the two carried nits. Branch `phase-44-b2`, from `origin/main`;
its first commit is this review.

**Decided:**
1. **Step 0.** Confirm `main`'s push run 45216449983 on `f694cb6` by id.
2. **Lexical format classes (F44-011).** Rows in the shared `formats` fixture
   first: `1`, `0`, `4`, `22`, `8080` and `65500` are `numeric`; `true`, `Off`
   and `yes` are `booleanish`. Before changing the rule, `git grep` every
   reader of `port` and `booleanish`; if any rule depends on them, stop and
   raise it. `docs/UPGRADING.md`: re-capture after upgrading, as for Q42.
3. **The working directory joins the identity rule (F44-012).** In the process
   adapter, the directory is injected like the hostname, a variable equal to
   it is recorded present with its value unshaped, and the capture's meta
   counts it. Nothing is keyed on a name.
   - **Test:** `verify` over two process captures from one kind of shell, at
     different depths and directories, finds no difference in `SHLVL` or
     `PWD`; the same change on a variable that is neither the directory nor a
     counter still counts.
   - **Docs:** LIMITS says the process adapter records the environment it is
     launched in, the launcher's own variables included, so `diagnose` and
     `verify` are launched the same way; the GUIDE's tour captures from a
     clean environment (`env -i` with `PATH` and `HOME`).
4. **Observations are not configuration (F44-055).** Each CONFIGURED predicate
   declares whether it is configuration or an observation, where it is
   defined, read by Go and Python from one place. `verify` counts
   configuration only; an observation that changed appears in the record as
   one, never as `changed_underneath`.
   - **Test:** a pair of captures differing only in a DNS observation is not
     `changed_underneath`; the same difference on a configuration predicate
     still is.
5. **Severity's third state (F44-063, F44-064 c).** A component reachable from
   an entry point only through an edge of `unknown` criticality gets severity
   `unknown`, naming the edge. Go's `severity` and Python's
   `upstream_connections` read one fixture under `shared/tests/`. UPGRADING
   says where findings' severities change.
6. **Honest absence.**
   - **F44-010:** the migration-head reader reads a tuple `down_revision`, a
     merge; the `c09` fixture first.
   - **F44-013:** the Kubernetes capture is never complete from a Deployment
     template alone, since the image, `envFrom` and admission webhooks add
     keys it cannot see. It says which sources it could not read, and judges
     no key missing.
   - **F44-057:** an unreadable or too-deep part of a repository is a skipped
     entry naming its path, in every extractor.
   - **F44-058:** a migration file that does not parse is named as unreadable,
     and a chain with an unreadable file yields no "not migrated" finding.
   - **F44-090:** a key that is not valid UTF-8 is named as unreadable, its
     bytes escaped, and never becomes a subject.
7. **Two readers, one value (F44-064 a, b).** The snapshot diff and
   never-render-a-value each get one fixture under `shared/tests/` that Go and
   Python both read.
8. **Q46.** `probe.auth.propagation` takes `token_env`, read in the agent's
   memory only, as `token_shape` does; its catalogue version rises, and its
   422 no longer says it cannot be sent.
9. **The nits.** `token_env=NAME` becomes an `over_redacted` row with its
   `why`. Every MCP tool that can run a manifest's command sets `readOnlyHint`
   false.

**Do NOT:**
- change a verdict rule beyond decision 4, or the shape vocabulary;
- move a fact between planes, or key anything on a list of names;
- change the fault library's expectations: if an outcome in `results.json`
  changes, stop and raise it;
- publish, release or deploy anything, or touch the ruleset.

### Review of batch 2 — facts that hold, merged as `760cdfd` (PR #73), 2026-11-24

**Signed off, subject to batch 3's step 0** attributing `main`'s red `e2e
(none)` (below), and with Q47's correction first in batch 3. The fault
library's expectations and results did not move, and every new rule is a gate
a mutation turns red.

**CI.** Read by id from GitHub's API:
- 45232041694 on `5ed4057` (the merge result) and 45234466757 on the report,
  `0f55a43`: success on every job; `publish` and `deploy` skipped, as on every
  pull request.
- 45229026168 on `6d9c8c8` was red on `kind-capture` only: it still asserted
  that a readable cluster gives no skip, the claim F44-013 withdrew. Fixed in
  `5ed4057` to expect the template's one skip and its reason. Attributed; not
  a flake.
- `main`'s push run 45425513632 on `760cdfd`: **failure.** `e2e (none)` failed
  at "Quickstart, under a pseudo-terminal", two and a half minutes into
  building the images, so `narration-parity` was skipped and `gate` failed,
  while the same tree (`0f55a43`, `eb39f47`) passed that job on 45234466757
  the day before. Every `build` job passed, and all five `publish` jobs pushed
  and attested anyway: F44-008 again. Not attributed here: job logs need a
  token. Batch 3's step 0 reads the log, reruns, and fixes it first if it is
  ambient.
- **Every commit is Verified,** `bc4e833` to `0f55a43` and the merge
  `760cdfd`. `bc4e833`'s tree is exactly the review patch's.
  `cli/testdata/faultlib/` and `demo-services/faults/` are unchanged from
  `f694cb6`.

**Verified here,** on `760cdfd` (Go 1.27.0):
- `go test` in `model`, `capture`, `verify`, `severity` and `diverge`: ok. The
  shared shape, capture-diff, request-path, verification and render tests in
  Python: 215 passed.
- **Four mutations of its own, each red and restored:** severity following an
  edge of unknown criticality as on the request path (the request-path fixture
  red); the identity rule keyed on the names `PWD` and `HOSTNAME` (the
  identity test red, as the rule must be an OS fact); `dns_resolves` declared
  configuration (three tests red, among them "an observation that changed is
  not a change underneath"); Python's `booleanish` taking `1` and `0` again
  (the `formats` fixture red).

**The run's decisions, accepted:**
- The brief's `verify` test for F44-012 was not red before the change, as the
  run said: paths are one class at any length, and F44-011 had already fixed
  `SHLVL`. The capture test holds the rule; the `verify` test holds the
  comparison. Accepted.
- An unflagged, older verification is judged as before, so stored records
  still validate; UPGRADING upgrades the control plane first. Accepted.
- Go disagreed with Python on two capture-diff cases and moved to Python's
  safe side (a one-sided key keeps its other questions; an unparseable subject
  is never printed). No verdict moved. Accepted.
- `readOnlyHint` is true for `system_model`, `check` and `explain_connection`
  only under `--no-plugins`; `probe`, `diagnose` and `verify` are never
  read-only. Accepted.

**Rulings:**
- **Q47, what an incomplete capture may still say.** Incompleteness is about
  what Culprit could not see; it must never hide what it did see. When both
  captures read a Deployment's template, a key one template lists and the
  other does not is a difference, worded as a change to the template ("no
  longer listed; it may now come from a source Culprit cannot read"), and it
  counts in `verify` and `env diff`. A key from a source neither capture read
  is never compared, and absence is still never evidence against INTENT. My
  F44-013 ruling over-reached; this corrects it. The CLI and the stored diff
  (`GET /captures/diff`) agree, from rows in `capture_diff_conformance.json`.
- **Q48, `unknown` and the gate.** A finding Culprit cannot classify must not
  pass the default gate silently, and must not be guessed as breaking either.
  For `--fail-on`, `unknown` counts as `degrades`: the default fails on it,
  `--fail-on=breaks_request_path` does not. The output says why. UPGRADING and
  LIMITS correct batch 2's note.
- **F44-014, a claim's deadline.** A claimed task not completed within its
  deadline is failed with a reason naming the claim's time and the deadline;
  it is never re-queued, since a probe may have run part-way. The deadline is
  the task kind's own timeout plus a margin, 15 minutes by default, set on the
  server. Expiry is applied when tasks are read, with an injected clock: no
  new background service. An agent that restarts fails its own unfinished
  claims instead of skipping them.
- **F44-042, sessions after a password reset.** LIMITS states the windows now;
  a token version is deferred past the field trial, whose control plane is a
  local quickstart with one user.
- **F44-043, request size.** Measure the largest body a legitimate client
  sends in the e2e and fault-library runs, and cap `/api/*` in Caddy and in
  the signed-route dependency with a margin of four times that. LIMITS names
  the number; a 413 names the limit.
- **F44-008** needs no ruleset change: `gate` stays the one required check,
  and the new publish job needs `gate` on pushes and tags only.

### Batch 3 — reliable under strain (brief, 2026-11-24)

**Findings:** Q47 and Q48 first, then F44-008, -009, -014, -015, -039, -040,
-041, -042, -043, -044, -047 and -050. Branch `phase-44-b3`, from
`origin/main`; its first commit is this review.

**Decided:**
1. **Step 0: attribute `main`'s red push run first.** Run 45425513632 on
   `760cdfd` failed `e2e (none)` at "Quickstart, under a pseudo-terminal", two
   and a half minutes into building the images, while the same tree passed
   that job on 45234466757 the day before. Read the failed log (`gh run view
   45425513632 --log-failed`), attribute the cause, then rerun the failed jobs
   (`gh run rerun 45425513632 --failed`) and record both by id.
   - **If an input outside the repository moved** (a base image, an unpinned
     package, a registry), it is ambient: fix it first in this batch, in its
     own commit, and never by weakening the job. **If it was the runner,** it
     becomes a finding with its cause (D6). **If the cause is in the code,**
     stop and raise it.
2. **Q47,** as ruled: rows in `capture_diff_conformance.json` first (a key in
   one template and not the other is a difference; a key from an unread
   `envFrom` source is not compared), read by `verify.Differences`, `env diff`
   and the stored diff. Test: two Kubernetes captures whose templates differ
   by a key are not `verified` past it. Update `kind-capture` only if its
   expectation changes, and say why.
3. **Q48,** as ruled, with the CLI's `--fail-on` tests shown red first.
4. **Publish waits for `gate` (F44-008).** Images are built and scanned as
   now, passed as artifacts, and pushed, attested and verified in a job that
   needs `gate`, on pushes to `main` and tags only. `gate` never needs it.
   `test_ci_workflow.py` asserts "publish needs gate" first. Proof: `main`'s
   push run after the merge.
5. **The quickstart over an older env file (F44-009).** Backfill every key
   `bootstrap_env.py` generates that the file lacks; never overwrite or
   regenerate a key that is there. A script test over an env file without
   `NARRATOR_DB_PASSWORD` fails first.
6. **A claim's deadline (F44-014),** as ruled, tested in `api/tests` with a
   claim and an injected clock.
7. **The API under strain.**
   - **F44-015:** trust `X-Forwarded-For` from the one Caddy hop the compose
     files declare, never from any address; the per-address limit shown per
     address.
   - **F44-041:** "planted or real, never both" becomes a constraint in a new
     migration, round-trip tested. If existing rows would violate it, the
     migration stops and says how many and what to do; it never alters or
     deletes a row.
   - **F44-043:** the measured cap, as ruled.
   - **F44-044:** one error shape, the one most routers already use, defined
     once; every router's errors pass through it; `frontend/src/lib/api.ts`
     reads that shape only; a test fails first on a route that answers in
     another.
   - **F44-047:** a unique violation on a create is a 409, tested with two
     concurrent sessions.
   - **F44-050:** CORS origins are trimmed.
8. **The worker under strain.**
   - **F44-039:** an entry Postgres refuses is quarantined with its reason, as
     LIMITS already says of poison messages, and the drain carries on.
   - **F44-040:** the drain lock is released only by its holder,
     compare-and-delete with a token, and renewed while held.
9. **F44-042:** the LIMITS entry, as ruled.

**Do NOT:**
- delete, alter or re-label a stored row, or drop anything; new migrations
  only, each round-trip tested;
- re-queue a task automatically, or add a background service;
- change the ruleset or `gate`'s needs; a tag cannot be cut to prove the tag
  path;
- change the fault library's expectations: if an outcome changes, stop and
  raise it;
- publish, release or deploy anything beyond what `main`'s push run already
  does.

---

## §7. Readiness (the last part)

- **The regression pass.** Rerun the whole gate set and the end-to-end
  journeys on the final `main`. Every S1 and S2 finding is closed or put to
  the owner.
- **The fresh-clone walkthroughs.** Run one on Linux, in CI, and one on
  Windows, and record both.
- **`docs/FIELD_READINESS.md`.** A verdict — ready, ready with conditions, or
  not ready — with:
  - the evidence for each criterion in §1;
  - every open finding and risk;
  - what could not be tested.
- **The field-trial runbook,** in `docs/GUIDE.md` or in a file of its own, as
  the review decides.
