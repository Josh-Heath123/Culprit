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

---

## §6. Batches (written by the reviews)

The review that rules on each batch writes that batch's brief here.

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
