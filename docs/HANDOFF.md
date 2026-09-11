# Handoff — the baton between architecture and execution

This file is the state carrier for Culprit's development. It exists because the
architecture conversation and the implementation session are different places,
and a decision that lives only in a chat transcript is a decision that gets made
twice.

**Protocol.**

- **The architecture session writes** §2 (Decisions), §3 (Open questions) and the
  *Brief* line of the current phase in §4. It never writes run reports.
- **Claude Code writes** §4 status transitions and §5 (Last run). It never
  answers an open question in §3 on its own — it surfaces the question and stops.
- **Both read the whole file first.** It is committed, so `git log docs/HANDOFF.md`
  is the decision history.

**CI is part of the gate set.** A phase is not complete until CI is green on the
**merge result** — `origin/main` merged into the branch — not on the branch
alone. Local `/verify` covers neither: it runs a subset of the checks, on a tree
that is not what gets merged, on Windows rather than Linux. Run `/ci` before
reporting any phase complete.

**Committing.** Use `git commit -F <message-file>`. The
`-m "$(cat <<'EOF' ...)"` form triggers a permission prompt on command
substitution every single time — that is the permission system working correctly,
not a misconfiguration, and it has blocked three phases in a row.

**The one rule that makes this work:** a phase does not advance on a red gate,
and Claude Code does not auto-start the next phase. One human keystroke per
phase is not friction — it is the review checkpoint, and it is the only place a
wrong architectural turn gets caught before it is built on.

---

## §1. Where things stand

| | |
|---|---|
| Plan of record | `docs/DIAGNOSTIC_PLAN.md` (Phases 26–35) |
| Current phase | **30 — Environment capture and cross-environment diff** — status **`gates red`** (on `main`; CI red; one fix staged, one decision pending — Q14) |
| Status | Phase 30 committed as `c5ce4eb` and pushed **directly to `main`** (no PR). CI run 34499505671 is **red** on two jobs, both pre-dating Phase 30 and neither caused by its code: `build (frontend)` fails the Trivy scan on 12 CVEs (1 CRITICAL) compiled into upstream `caddy:2-alpine`'s binary, red since 2026-09-09; `self-check` fails at "Upload SARIF" (`Resource not accessible by integration`), red since Phase 29 added it, and has never passed — the repo is private, the job lacks `actions: read`, and code scanning is not enabled. Deploy was skipped, so the VM does not run Phase 30. **Not complete by invariant 12.** |
| Branch | `phase-30-env-capture` = `origin/main` = `c5ce4eb`, plus the **staged, uncommitted** Caddy fix (`frontend/Dockerfile`, `.trivyignore` note, LIMITS, this file, CLAUDE.md). `git commit -F` was denied twice on 2026-09-11, so nothing is pushed and no PR exists. Message: `scratchpad/commit-caddy.txt` in session `40d640d0`, reproduced in §5. Do not stage `shared/uv.lock` (a stray). |
| Blocking questions | **Q14 (§3) blocks completion** — the `self-check` SARIF upload, a decision about the repository. The frontend Trivy failure is *not* a question any more: fixed by building Caddy from source (staged, verified locally, CI not run). **Deploy hazard:** the first green `main` run deploys Phase 30, so `CAPTURE_WRITER_*` must be in the VM's `.env.prod` *before* the fix merges. Deploy needs only `build`, not `self-check`, so the Caddy fix alone is enough to trigger it. Non-blocking Q9–Q13 unchanged. |
| Last gate run | 2026-09-11, `/ci` on `c5ce4eb`: every local gate green (lint, typecheck, lint-imports, schema drift, `just test`, coupled files, self-check incl. `LLM_PROVIDER=none` — 987 facts/435 subjects locally vs 878/370 in CI, unexplained). CI: lint, typecheck, cli, test, migration-round-trip, kind-capture, build(cli) PASS; self-check, build(frontend) FAIL; build(api/worker/mcp_server) cancelled; deploy skipped. The 2026-09-10 "Trivy run locally" green did not match CI's result. |

Phase 25 (memory visualisation) is **cancelled**. Do not implement it.

---

## §2. Decisions register

Decisions made and not to be relitigated per session. Architectural decisions
D1–D8 live in `docs/DIAGNOSTIC_PLAN.md` §1 with their alternatives and revisit
triggers; this section records the session-level ones and anything that
supersedes the plan.

| Date | Decision | Rationale |
|---|---|---|
| 2026-09-08 | Evolve the existing repository. No new repo. | Requirements changing is normal; the substrate (role model, CI, ingest, Timescale/pgvector) is real capital. |
| 2026-09-08 | Target user is solo developers and small teams without SRE/DevOps. Not enterprise. | Determines that the CLI wedge outranks the production agent in sequencing. |
| 2026-09-08 | Deterministic core; AI optional. `LLM_PROVIDER=none` must produce complete correct output from every command except prose. | This is the product's defensible property and is enforced as a CI job, not an aspiration. |
| 2026-09-08 | Tier-3 business-logic correctness is out of scope permanently. | No oracle exists. Promising it fails the product's own standard on first contact. The shippable version is the unverifiable-surface report (Phase 29). |
| 2026-09-08 | No `mutate`-effect probe and no `*.write` capability in this entire plan. | Structural boundary, not a config flag. Adding one requires its own plan document. |
| 2026-09-08 | Historical baseline is a statistic over `OBSERVED`, never a fourth plane. | Treating "usual" as a proxy for "correct" is the exact mistake the rewrite exists to fix. |
| 2026-09-09 | `configured_facts.value` is NULL unless `grant_ref` names an explicit per-key grant, enforced by a CHECK constraint. Facts carry `value_shape`. | Resolves Q3. A convention against storing credentials is not a control. Nearly free now (table empty), a migration over live data after Phase 30. |
| 2026-09-09 | An `invariants:` entry is an ordinary INTENT fact at confidence rank 100, not a separate assertion engine. | Keeps the comparator generic (D7): the same code path handles a human's assertion and an extractor's, including severity, suppression and SARIF. Consequence, accepted: an invariant that is *wrong* produces a loud finding rather than being quietly overruled by the code — which is correct, because a stale assertion is a real defect. |
| 2026-09-09 | Rank says how much to believe a source; it does not say the source enumerated. Absence is judged only against sources that survey a surface (rank ≥ 80 and not a developer assertion). | Learned by defect: a single rank-100 invariant became a component's "complete" route list and reported the application's real routes as absent. The two properties had been conflated. |
| 2026-09-09 | The `culprit` binary makes no network call. `internal/check` links no networking package at all, asserted against `go list -deps`. | Turns field 17's "no LLM anywhere near this path" from a list of vendor names into a structural property. An uploader belongs with Phase 30's capability model, where network access can be gated. |
| 2026-09-09 | `fact-writer` is extended to `divergences` rather than a twelfth role being added. Second sanctioned exception to `.claude/rules/database.md`. | Same CI run, same repository, same project token, same blast radius as the facts it derives from. A second password in every CI configuration, issued to the same process for the same purpose, is friction with nothing gained. The role test was rewritten *stronger*, not weakened — see §5. |
| 2026-09-09 | Phase 26 acceptance criterion 1 reworded; the 10s key cache stays. | Resolves Q4. The original wording was untrue and making it true would put a DB round trip on the ingest hot path. The defect fixed was that revocation previously worked only by accident. |
| 2026-09-09 | The `value_shape` hole is real. Fix is a closed `ValueShape` type in `culprit_model`, landing in Phase 28, not a wider CHECK constraint. §2.2's claim narrowed immediately to what is actually true. | Resolves Q5. A DB constraint cannot protect a capture bundle that is serialised and never inserted — which is exactly the artefact the guarantee is about. Enforcement belongs in the type. |
| 2026-09-09 | **Permission rules were never matching.** All 31 `Bash(cmd *)` rules rewritten to `Bash(cmd:*)`, the actual prefix syntax. | Four consecutive commit denials of a command sitting in `allow`. My error, not the commit form — `-F` was never the problem. Also the cause of the hung editor. |
| 2026-09-09 | Invariant 11: error text is output, subject to the same redaction as a fact, enforced at one serialiser rather than per call site. | Phase 28 found four exfiltration paths through errors; three were introduced by the fix for the previous one. Per-site redaction always has one more site. |
| 2026-09-09 | `ValueShape` carries `scheme` as a closed enum, not a free string. | Resolves Q7. Declared-`postgresql` vs deployed-`mysql` is a real, undetectable-without-it fault class. A closed enum cannot carry a secret. |
| 2026-09-09 | Extraction uses synthetic import-time environment values. The user's real `.env` is never sourced, and there is no option to. | Resolves Q8, and follows from invariant 11: the only safe extractor process is one that never held a credential. |
| 2026-09-09 | Criterion 2 says what determinism means: byte-identical with `SOURCE_DATE_EPOCH` pinned. Publication moved from Phase 28's DoD to Phase 29's. | The original criterion was unsatisfiable while facts carry timestamps. Publishing before the tool is useful burns package names and invites installs against a CLI that only prints an inventory. |
| 2026-09-09 | Invariant 10: a new gate is not accepted until a deliberate mutation makes it fail, targeting the mechanism believed to be load-bearing. | Phase 27's mutation of the round-trip gate stayed green — the gate was fine, the belief about *why* it worked was wrong. A passing check is not evidence until shown it can go red. |
| 2026-09-09 | `culprit.yaml` round-trip criterion is semantic equality plus a fixed point, not byte equality. Plus a new criterion that `--export` must not silently destroy a hand-maintained file. | Resolves Q6. Byte equality from the first export tests comment preservation — a human convenience, not a model correctness property. The substitution was an honest correction, not a weakening. |
| 2026-09-09 | Commit with `git commit -F <file>`, never `-m "$(cat <<EOF...)"`. | The heredoc form triggers a permission prompt on command substitution every time — correct behaviour, but it has now blocked three phases running. `-F` matches the allow rule cleanly. |
| 2026-09-09 | Two new standing invariants: migrations round-trip tested against a real DB in CI (8); every check's scanned roots covered by a test (9). | Phase 26.1 shipped a downgrade defect the AST symmetry checker structurally cannot see, and two consecutive phases found violations hiding outside a check's scanned roots. Both gaps are now gates. |
| 2026-09-09 | Go for `cli/` — one static binary, CLI and probe agent. | Resolves Q1. D2's revisit trigger stands: ~6k lines by end of Phase 29, or control-plane logic leaking in, means the boundary is wrong. |
| 2026-09-09 | Product first; phase order unchanged. Phases 29, 30 and 32 each also produce a recorded demo and a short written account. | Resolves Q2. The usable-early ordering is also the better portfolio story; capturing it costs an hour per phase and nothing architecturally. |
| 2026-09-09 | `CLAUDE.md` gets an explicit size budget (8 KB), tracked separately from accuracy. | It grew 32.5 KB → 37.2 KB during Phase 26. Accuracy was the stated criterion and was met; size was never a criterion, which was an ambiguity in the brief, not a failure of execution. |

---

## §3. Open questions

Claude Code must not answer these. It surfaces them and stops.

**Q1 — RESOLVED 2026-09-09: yes, Go.** `docs/DIAGNOSTIC_PLAN.md` D2 stands as
written. `cli/` is a Go module producing one static binary that serves as both
the developer CLI and the deployable probe agent. Keep it small and behind the
versioned JSON contract in D3 — the revisit trigger in D2 still applies: if the
Go surface passes ~6k lines by the end of Phase 29, or starts absorbing logic
that belongs in the control plane, the boundary is wrong.

**Q2 — RESOLVED 2026-09-09: product first, portfolio deliberately.** Phase
ordering is unchanged — 29 and 30 stay ahead of 31 and 32, because a thing a
stranger can install and use in sixty seconds is both the better product and,
in the end, the better story. Additional standing obligation: Phases 29, 30 and
32 each produce a recorded demonstration against a real fault and a short
written account of what the engine established and how. Do it at the end of the
phase, while the detail is fresh. No architectural consequence.

**Q7 — RESOLVED 2026-09-09: yes, `scheme`, as a closed enum.** Recorded in
`docs/DIAGNOSTIC_PLAN.md` §2.2. The general rule it sets: any field added to
`ValueShape` must be expressible as a closed set or a bounded numeric class, or
it does not belong in the type.

**Q8 — RESOLVED 2026-09-09: synthetic values only.** `culprit.yaml`'s `extract:`
section declares the variable *names*; the CLI generates shape-satisfying
synthetic values. The user's `.env` is never sourced and no flag enables it. An
app that cannot import without a live connection yields `skipped` with that
reason. Recorded in `docs/DIAGNOSTIC_PLAN.md` D3.

**Q6 — RESOLVED 2026-09-09.** Rewording accepted; it was a correction, not a
weakening. "Apply, export, diff is empty" was never the property that mattered —
byte equality from the first export tests comment preservation, which is a
convenience for humans editing the file, not a correctness property of the model.
Semantic equality plus a fixed point tests exactly what the criterion is for.
Applied to `docs/DIAGNOSTIC_PLAN.md` Phase 27, field 14, together with a new
criterion: `--export` must not silently destroy a hand-maintained file, since
comment loss is real even if it isn't a correctness bug. Keep the LIMITS.md
split you wrote between unavoidable normalisation and design choice.

**Q5 — RESOLVED 2026-09-09.** You were right and the plan was wrong. The CHECK
guards `value`, the column extractors are told not to use; `value_shape`, the
one they are steered toward, was unconstrained. And `culprit_model.Fact` carries
neither field, so Postgres was the only enforcement point — leaving a serialised
capture bundle, the artefact the promise is actually about, unprotected. Fix is
a closed `ValueShape` type in `culprit_model`, scheduled into Phase 28 (fields 4
and 14) rather than bolted on now, because that is where Facts are first
constructed and serialised for real. `docs/DIAGNOSTIC_PLAN.md` §2.2 has been
narrowed to claim only what is true in the meantime. Keep the LIMITS.md wording
you wrote — it was already the accurate one.

**Q3 — RESOLVED 2026-09-09.** Yes, make it structural. `configured_facts`
gains a `grant_ref` column and a CHECK constraint `value IS NULL OR grant_ref IS
NOT NULL`; facts carry `value_shape` instead of `value` by default. Recorded in
`docs/DIAGNOSTIC_PLAN.md` §2.2. See the prerequisite task in §4 — this lands
before Phase 27 work begins, while the table is still empty.

**Q4 — RESOLVED 2026-09-09.** Rewording accepted verbatim and applied to
`docs/DIAGNOSTIC_PLAN.md` Phase 26, field 14. The code is correct; the criterion
was wrong. Good catch — that is precisely the kind of plan defect the audit step
exists to surface.

**Q5 — Should `value_shape` have a closed key vocabulary?** (Raised by the 26.1
invariant audit. Does not block Phase 27; wants deciding before Phase 30 writes
real captures.)
26.1 did exactly what its brief said and the CHECK constraint holds, but the
guarantee is narrower than §2.2's sentence "Config values are structurally
excluded, not conventionally" claims. The constraint protects `value` — the
column the design tells extractors *not* to use. `value_shape`, the column it
steers them *towards*, is free-form JSONB, and
`{"type":"url","sample":"postgresql://u:hunter2@db/orders"}` inserts happily
with no `grant_ref`. Verified by execution, not inferred.

So the credential-in-Postgres failure mode Q3 was raised about is reduced, not
closed. §2.2 already defines shape as type / length class / format class, so the
vocabulary is finite and a CHECK over `jsonb_object_keys` (or a `ValueShape`
model in `shared/culprit_model` with a negative test) would close it. Two things
for the architecture session: whether to do that, and whether §2.2's wording
should be narrowed in the meantime, since as written the plan overstates what
the schema does. Related and cheaper: `grant_ref = ''` currently satisfies the
constraint.

Claude Code did not do either — both are outside 26.1's "nothing else" brief.
`docs/LIMITS.md` and the migration docstring were narrowed to state the real
scope rather than the claimed one.

**Q6 — Should `connections` carry an authored order, and should
acceptance criterion 2 be reworded?** (Raised by the Phase 27 phase audit.
Does not block Phase 28.)

Two related things, both about `culprit.yaml` round-tripping.

*The wording.* Criterion 2 says "apply, export, diff is empty". Two of the
three ways an export differs from a hand-written file are unsatisfiable by
any database-backed round trip, not defects: YAML comments live in the
parser rather than the document, and "did the author write `kind: http`
explicitly or leave it to the default?" is not information the schema
stores — `connections.kind` holds `http` either way. Phase 27 therefore
checked the criterion as *semantic* equality (the exported manifest parses
to a `Manifest` equal to the applied one) plus a fixed point (export is
byte-identical on re-export, and re-applying reports zero writes), and
documented the normalisation in `docs/LIMITS.md`. The phase auditor judged
that an honest satisfaction rather than a weakening, and proposed:

> `culprit.yaml` round-trips: applying a manifest, exporting, and
> re-applying the export produces no writes; the exported manifest parses
> to a `Manifest` equal to the applied one; and export is a fixed point
> (exporting an exported file is byte-identical). The exporter emits a
> canonical form, so a byte diff against a non-canonical hand-written file
> is not expected.

Worth adopting into `docs/DIAGNOSTIC_PLAN.md` so the next auditor can
execute it without a judgement call.

*The choice underneath it.* The third difference — each component's
connections being sorted by `(to, kind)` — is **not** unavoidable.
Component order survives because `apply_manifest` records each
component's file position as its `sort_order`; the identical mechanism
was available for connections and was not used, and `connections` has no
`sort_order` column. Adding one would bring the export nearer the literal
criterion at the cost of a column that exists only for presentation.
Claude Code did not decide this either way; `docs/LIMITS.md` now marks
that bullet explicitly as a design choice rather than a necessity.

**Q7 — Should `ValueShape` carry a `scheme`, or something like it?**
(Raised by Phase 28. Does not block Phase 29; wants deciding before
Phase 30 writes real CONFIGURED captures.)

The four-field shape was fixed by decision (§2, 2026-09-09) and Phase 28
implemented it exactly. Now that it exists against real data, the cost is
measurable rather than hypothetical: **a `DATABASE_URL` pointing at
`postgresql://` in staging and `mysql://` in production has the same
shape**, and so does a hostname change, a port change, and any two
secrets of similar length. Shape comparison catches "set versus unset",
"empty versus populated", "a DSN where a bare hostname was expected" and
"credential-shaped where it should not be". It does not catch "pointing
at the wrong thing", which is a large share of the config faults this
product exists to find.

A `scheme` field constrained to a closed enum (`postgresql`, `mysql`,
`redis`, `https`, …, `other`) would close most of that gap without
reopening the hole — it cannot carry a literal any more than `format`
can. §2.2's own original example had one. But it is a widening of a
decided field set, and widening "the type a literal cannot fit in" is
exactly the change that deserves a deliberate decision rather than an
implementer's judgement.

Recorded in `docs/LIMITS.md` as a stated limit in the meantime.

**Q8 — How should a user supply import-time environment for extraction?**
(Raised by Phase 28. Does not block Phase 29; it is an adoption problem,
not a correctness one.)

Runtime introspection imports the application, and a great many
applications read required configuration at import time — this
repository's own API raises `KeyError: JWT_SECRET_KEY` and yields no
routes and no schema without values for six variables.

`culprit.yaml` is the obvious place to put placeholders and is the wrong
one: it is a committed file that names config keys and never carries
values, and its loader refuses anything credential-shaped. That refusal
fired the first time placeholders were tried there, which is the loader
working correctly. So Phase 28 put them in `just intent` instead — fine
for this repository, useless for a user's, which has no justfile.

The options, none obviously right:
- An `env:` block on an extractor spec, with the credential refusal
  applied to it. Convenient, and it puts a values-shaped thing in the one
  file whose whole discipline is that it holds no values.
- Nothing in the manifest; document that the caller sets the environment.
  Honest, and pushes a real papercut onto every user in CI.
- An `env_file:` pointer to a gitignored file the extractor command
  reads. Keeps values out of the committed manifest, adds a file whose
  absence is a confusing failure.

Worth settling before Phase 29 ships to strangers, since "I ran it and
got nothing" is the first impression this decides.

**Q9 — Is the Go surface still the right boundary?** (Raised by Phase 30.
Does not block Phase 31.) Q1's revisit trigger (~6k lines) had already
fired at 6,060 non-test lines; Phase 30 took `cli/` to 10,139. Most of the
growth is capture (adapters, database, network, envelope) and the
permission model — logic that has to run where the environment is, which
is D2's argument for Go. But the trigger exists to take that judgement
out of the implementer's hands.

**Q10 — Should the CLI upload, and must captures be signed?** (Raised by
Phase 30. Does not block Phase 31.) LIMITS promised Phase 29's deferred
uploader would arrive "with the capability model"; Phase 30's fields
list the endpoints but not an uploader, so the binary still links no
HTTP client (a test asserts it). Separately, field 7 says "signed", and
signing is optional because it needs a key the user holds; an unsigned
envelope can be edited and re-hashed, and neither `culprit diff` nor
`POST /captures` can be told to require a signature or pin key ids. Both
are decisions about what the binary is allowed to talk to and trust.

**Q11 — Should granted values be guarded by the database, not only the
API?** (Raised by the Phase 30 invariant audit. Does not block.) Three
residual risks, documented in LIMITS: `api-reader` can SELECT a granted
literal and only `fact_out` keeps it out of responses (a masking view
would make it structural); "a config value's grant is its own key's" is
checked by `POST /captures`, not by a CHECK; non-config values are not
type-checked on upload.

**Q12 — Where do DNS / TCP / TLS checks live?** (Raised by Phase 30.
Wants deciding before Phase 31.) Phase 30 field 4 asks capture for "DNS
resolvability, TLS certificate expiry, reachable ports"; Phase 31 lists
`probe.net.dns_resolve`, `probe.net.tcp_connect` and
`probe.net.tls_validity`. Phase 30 built them as passive CONFIGURED facts
(`component:X dns_resolves` etc.) that stop at a handshake, reading field
17 as "no application requests". Phase 31 should either re-site them as
probes or state that both exist and why.

**Q13 — `configured_facts`' Phase 26.1 CHECK covers every row.** (Found
by Phase 30; resolved in-phase without changing the constraint, recorded
for ratification.) `value IS NULL OR grant_ref IS NOT NULL` applies to
image digests and column lists too, so as written no non-config CONFIGURED
value could be stored. Rather than narrow a decided constraint, every
CONFIGURED fact now names the grant that permitted reading it
(`db.metadata.read`, `deploy.metadata.read`, or per-key
`config.read.values:<component>/<KEY>`), which `POST /captures` validates
against the capture's own grant list. If the architecture session would
rather narrow the CHECK to `config:` subjects (as `intent_facts`' is),
that is a one-migration change.

**Q14 — How should the `self-check` job's SARIF reach GitHub?** (Raised by
`/ci` on 2026-09-11. **BLOCKS Phase 30's completion** under invariant 12:
CI cannot be green while it fails.) The `self-check` job's last step,
`github/codeql-action/upload-sarif@v3`, fails with `Resource not
accessible by integration`, and has failed on every run since Phase 29
added it — it has never passed. The `culprit check` steps before it
succeed and write a valid SARIF file. Two causes, stacked: the job's
`permissions:` block (`ci-cd.yml` ~222–228) grants `contents: read` and
`security-events: write` but not `actions: read`, which upload-sarif
needs on a private repository; and behind that, `code-scanning/analyses`
returns 403 `Code scanning is not enabled for this repository` — on a
private personal repository that is a paid feature. Adding `actions: read`
alone would only move the failure. The options, each a human's call:
- **Make the repository public.** Code scanning is free; fits the MIT,
  self-hosted direction and the still-outstanding public ghcr.io packages.
  Irreversible in practice (the history is published).
- **Keep it private and pay for GitHub Code Security.**
- **Keep it private and publish `culprit.sarif` with
  `actions/upload-artifact` instead,** dropping the claim that Culprit's
  own pull requests get annotations. This removes a step that fails, so by
  the `/ci` rule it is not Claude Code's to do unilaterally.
Whichever is chosen, also add `actions: read` and move `upload-sarif` to
v4 (v3 is deprecated in December 2026). Claude Code has not touched the
job. `docs/LIMITS.md` states the gap in the meantime.

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
| 30 | Environment capture and cross-env diff | **gates red** | All four acceptance criteria met on real systems (criterion 4 after the audits failed it, correctly). On `main` as `c5ce4eb` (pushed directly, no PR). CI red on two jobs that pre-date it: frontend Trivy (fix staged, 2026-09-11) and `self-check` SARIF upload (Q14). |
| 31 | Probes | not started | Reconcile with Phase 30's passive DNS/TCP/TLS capture facts (Q12). |
| 32 | Fault isolation and the Investigation | not started | — |
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
Run:          2026-09-11, /ci then /next — Phase 30, gates red. Phase 31
              NOT started.
Status:       gates red. Phase 30 is NOT complete (invariant 12).

WHAT /ci FOUND
  Phase 30 had been committed (c5ce4eb) and pushed straight to main, not
  via a PR, so origin/main == the branch and "merge origin/main" was a
  no-op: the tree tested IS the merge result. CI run 34499505671 on it:
    PASS  lint, typecheck, cli, test, migration-round-trip, kind-capture,
          build(cli)
    FAIL  build(frontend) — Trivy: 12 CRITICAL/HIGH in usr/bin/caddy
          (gobinary) from caddy:2-alpine. Red since 2026-09-09 (masked
          by tsc errors in Phases 27-28). Last green 2026-08-10.
    FAIL  self-check — "Upload SARIF": Resource not accessible by
          integration. Never passed since Phase 29 added it. -> Q14.
    CANCELLED build(api, worker, mcp_server) — so their Trivy status on
          current main is UNKNOWN.
    SKIPPED deploy — the VM does not run Phase 30.
  Neither failure is Phase 30 code. The 2026-09-10 report's "Trivy run
  locally, PASS" covered cli and api only, not frontend.

LOCAL GATES on c5ce4eb (all PASS)
  lint, typecheck, lint-imports, check-schema-drift, just test (832+86+
  21+31), check_coupled_files (vs origin/main: vacuous, base == HEAD; re-
  run vs a407542: PASS), check-invariants, self-check 0 divergences,
  LLM_PROVIDER=none self-check. Self-check sees 987 facts / 435 subjects
  locally vs 878 / 370 in CI — unexplained; likely locally-present
  generated files. Worth a look: the dogfood gate is not seeing the
  same thing in CI as on a dev machine.

WHAT THIS RUN CHANGED (staged, NOT committed)
  frontend/Dockerfile   new `caddy` stage: xcaddy v0.4.7 builds Caddy
                        v2.11.4 on golang:1.27-alpine (cli/'s toolchain)
                        with x/crypto v0.57.0, x/net v0.59.0, grpc
                        v1.83.2 via --replace; copied over /usr/bin/caddy.
  .trivyignore          a dated note: its five caddy entries no longer
                        protect the frontend; delete once api/worker/
                        mcp_server/cli are re-scanned without them. No
                        entry added or removed.
  docs/LIMITS.md        +2 sections: Caddy pinned by hand; Culprit's own
                        SARIF upload needs code scanning.
  HANDOFF.md, CLAUDE.md status corrected (they said "uncommitted, CI not
                        run" after it had been pushed to main); Q14.

  Verified locally (Trivy 0.72, fresh DB, same flags as CI):
    rebuilt frontend image, NO ignore file   -> 0 CRITICAL/HIGH (alpine 0,
                                                usr/bin/caddy 0)
    mutation: upstream caddy:2-alpine at CI's
    digest sha256:5f5c8640...                -> 17 HIGH in usr/bin/caddy
    caddy version v2.11.4, `caddy validate` on our Caddyfile: Valid,
    132 standard modules (stock build).
  NOT verified: CI on the fix (nothing pushed); the image actually
  serving the dashboard end to end.

COMMITTED:    NO. `git commit -F <file>` denied twice. Message file:
              scratchpad/commit-caddy.txt (session 40d640d0). Not pushed,
              no PR — and CI only runs on pull_request to main or pushes
              to main/tags, so a branch push alone would not run it.

AUDITS:       phase-auditor / invariant-auditor NOT re-run: no Phase 30
              code changed since both came back clean (below). The change
              is one Dockerfile stage and docs.

NOTICED, NOT ACTED ON
  - core.autocrlf is `true` (system gitconfig), not unset as CLAUDE.md
    says. Every Dockerfile in HEAD is CRLF; CI builds them fine.
  - upload-sarif@v3 is deprecated December 2026 (bump with Q14).
  - `self-check`'s first culprit-check step has continue-on-error: true
    (by design, for SARIF), so its exit code is invisible in step status.

TO FINISH PHASE 30 — a human
  1. Commit the staged work (message above), push, open a PR to main.
     CI on the PR tests the fix without deploying.
  2. Decide Q14 (SARIF) — the run stays red until then.
  3. Before merging: CAPTURE_WRITER_* into the VM's infra/.env.prod.
     Deploy depends only on `build`, so merging the Caddy fix deploys
     Phase 30 even while self-check is red.
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

Do not guess on any of these. Stop, write the question into §3, and stop.

- The plan's stated interface, data model or acceptance criterion turns out to be
  wrong or under-specified against the real code.
- Implementing a phase appears to require something on its own field-17 list.
- A gate can only be made green by weakening it — widening a `lint-imports`
  contract, adding a `# type: ignore`, skipping a test, widening a Postgres role.
- A decision in §2 would have to be reversed.
- Two intent sources disagree in a way the plan does not describe how to rank.
