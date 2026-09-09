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
| Current phase | **29 — The divergence engine** (not started) |
| Status | Phase 28 complete on its branch and **staged but uncommitted** — `git commit` denied at the permission prompt for the fourth phase running (§5). One command away; gates all green against the staged tree. |
| Branch | `phase-28-cli-extractors`. `main` has 26, 26.1 and 27 (`4f6e437`). |
| Blocking questions | **None.** Q1–Q6 resolved; Q7–Q8 raised by Phase 28 and neither blocks 29 (§3). |
| Last gate run | 2026-09-09, all green — 802 tests across five suites and three languages (§5) |

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
| 2026-09-09 | Phase 26 acceptance criterion 1 reworded; the 10s key cache stays. | Resolves Q4. The original wording was untrue and making it true would put a DB round trip on the ingest hot path. The defect fixed was that revocation previously worked only by accident. |
| 2026-09-09 | The `value_shape` hole is real. Fix is a closed `ValueShape` type in `culprit_model`, landing in Phase 28, not a wider CHECK constraint. §2.2's claim narrowed immediately to what is actually true. | Resolves Q5. A DB constraint cannot protect a capture bundle that is serialised and never inserted — which is exactly the artefact the guarantee is about. Enforcement belongs in the type. |
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

---

## §4. Phase ledger

Status values: `not started` · `in progress` · `gates red` · `awaiting decision` ·
`complete`.

| Phase | Title | Status | Brief |
|---|---|---|---|
| 26 | Truth repair and the three-plane schema | **complete** | Signed off 2026-09-09. All five acceptance criteria met (criterion 1 as reworded). Verification quality was the bar for every phase after this one. |
| 26.1 | `configured_facts` value safety | **complete, pending commit** | Signed off 2026-09-09. Caught two defects in the brief itself: the CHECK as specified would have inverted its own intent against `value NOT NULL DEFAULT 'null'::jsonb`, and the guarantee was narrower than §2.2 claimed. Both corrected. |
| 27 | The system model (the circuit) | **complete, pending commit** | Signed off 2026-09-09. Found two defects in the plan itself (field 11's networkx contradiction, criterion 2 unsatisfiable) and four real regressions in its own work, including `--export` laundering `declared_by` so a later apply could delete an accepted topology suggestion. Correlation ignoring `connections.kind` correctly deferred — now carried into Phase 32. |
| 28 | CLI, extractor protocol, intent extraction | **complete, pending review** | Signed off 2026-09-09. Both non-negotiables met: the closed `ValueShape` landed, and the corpus has four fixtures of which two are vendored verbatim from pallets/flask and expressjs/express. The third-party fixtures paid immediately — the Flask tutorial never touches `os.environ`, which exposed a limitation of the config reader that self-written fixtures could not have. Found and fixed four real defects of its own, including a CHECK constraint that let a *missing* key through and a coverage gate that stayed green under mutation. |
| 29 | The divergence engine | current | First shippable product. This is the wedge — treat its acceptance criteria as the real bar, especially "zero findings on a fixture known to be correct". Phase 28 left it a `culprit.yaml` at the repo root describing Culprit itself and yielding 931 facts, which is a ready-made comparison target. |
| 30 | Environment capture and cross-env diff | not started | — |
| 31 | Probes | not started | — |
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
Phase:        28 — The CLI, the extractor protocol, and intent extraction
Branch:       phase-28-cli-extractors (off 4f6e437, main)
Started:      2026-09-09
Finished:     2026-09-09

Scope note:   /next advanced ONE ledger row. Phase 29 was NOT started.
              Correction to §1 as found: it said Phase 27 was "staged,
              uncommitted" and that 28 was blocked on it. Both were
              stale — 27 was committed (d5ad2a6) AND merged (4f6e437)
              before this session began. No blocker existed.

              Go was not installed. Installed 1.27.1 via scoop (user-level,
              no admin). The phase requires it (D2, Q1 resolved).

Gates:        (from /verify; every one re-run after the audit fixes)
  lint                  PASS  (api+shared+scripts+examples, worker,
                               demo-services, mcp_server, extractors/python,
                               and now gofmt+go vet — see below)
  typecheck             PASS  (0 errors x5, plus frontend tsc 0 errors)
  lint-imports          PASS  (4 contracts kept)
  schema-drift          PASS  (16 worker tables match api's ORM)
  tests                 PASS  (api 705, worker 86, mcp_server 21, Go,
                               extractors/python 18, extractors/node 19;
                               4 skipped) — 849 across 5 suites, 3 languages
  coupled-files         PASS  (2 declared pairs, incl. one new)
  no-llm-imports        PASS  (9 packages across 3 languages)
  migration-symmetry    PASS
  scan-coverage         PASS  (213/213 Python files)
  migration-round-trip  PASS  (upgrade -> seed -> downgrade base -> upgrade)
  culprit check         NOT RUN — Phase 29 does not exist yet
  LLM_PROVIDER=none     NOT RUN — same

Acceptance criteria (executed, not inferred):
  1. `culprit intent` on a Python+React repository emits facts for
     server routes, client call sites, DB schema, migration head,
     config keys and dependency versions
       MET. Run against this repository's own new root culprit.yaml
       (culprit-api / culprit-web / culprit-worker / culprit-db /
       culprit-redis) — 943 facts:
         server routes        48   http:culprit-api/POST /postmortems ...
         client calls         31   retargeted onto culprit-api by calls_to,
                                   so they share subjects with the routes
         DB schema           368   schema:culprit-api-db/public.users.role
         migration head        2   from Alembic itself and from the file chain
         config keys         132
         dependency versions  90
       Nine skips, each naming a component and a reason.

  2. Running it twice on an unchanged tree produces byte-identical output
       MET, WITH THE CLOCK PINNED — and that qualifier is now a real
       feature, not a caveat. `captured_at` and the derived capture id
       are functions of the capture *time*; two runs seconds apart are
       two different captures of one tree and legitimately differ there.
       The CLI honours SOURCE_DATE_EPOCH, so:
         SOURCE_DATE_EPOCH=0 just intent --format json > a.json
         SOURCE_DATE_EPOCH=0 just intent --format json > b.json
         diff a.json b.json      # empty, 487 KB
       Verified twice: before the audit fixes and after. Everything else
       is deterministic by construction.

  3. A Fact about a config key cannot be constructed carrying a literal
     value — proved by attempting it
       MET. Attempted six ways, all refused: ValueShape(**{"sample": ...}),
       Fact(value=DSN) with no grant, with grant_ref="   ",
       model_validate_json on hand-written JSON, a hand-crafted POST body
       (422), and an extractor emitting one (dropped by the orchestrator
       and reported). ValueShape has four fields, every one a closed enum
       or a bool; a test asserts that over model_fields so a fifth
       free-text field fails rather than silently reopening the hole.
       Verified over 943 real facts: zero config literals. Strengthened
       twice after audit: the subject must now be canonical (a
       non-canonical `config:` subject bypassed both this check and the
       database's), and every ValueShape field is required (a shape
       missing `present` was being completed to `true` — a claim the
       extractor never made).

  4. With no extractor installed it still emits artefact-derived facts
     and reports precisely what it skipped and why
       MET. Fixture repo, extractor command deliberately absent: exit 0,
       7 facts (OpenAPI routes, .env.example keys and shapes, a
       dependency version), and a skip per want reading
       `extractor "python" could not be run: executable file not found`.
       No config value in the output.

  5. One static binary, no runtime installed, curl | sh documented
       MET, WITH ONE PART UNMET AND NOT MINE TO DO. The binary is
       genuinely static (`file` says "statically linked", CGO_ENABLED=0);
       all five release targets cross-compile (linux/darwin x
       amd64/arm64, windows/amd64); scripts/install.sh is valid POSIX sh
       and documented in docs/EXTRACTOR_PROTOCOL.md §11.
       NOT MET: no v0.1.0 release exists, so install.sh has nothing to
       download. .github/workflows/cli-release.yml publishes on a tag
       push and refuses a tag disagreeing with VERSION — cutting the tag
       is a human action.

Definition of done:
  The five criteria above       MET, except the release above
  Published v0.1.0 binaries     NOT DONE — needs a human to push a tag
  Published extractor packages  NOT DONE — culprit-extract-python is not
                                on PyPI, culprit-extract-node not on npm.
                                Both install from this repo as path
                                dependencies; publishing is an account
                                action, not a code change.
  docs/LIMITS.md updated        MET (11 new entries, 2 rewritten)
  docs/EXTRACTOR_PROTOCOL.md    MET
  CLAUDE.md status current      MET
  docs/HANDOFF.md updated       MET (§1, §3 Q7/Q8, §4, §5)
  Committed                     NOT DONE. `git commit` was denied at the
                                permission prompt — the FOURTH phase in a
                                row (26, 26.1, 27, 28), and this time in
                                the `-F <file>` form §2's own decision
                                prescribes for exactly this reason, so
                                that decision has not fixed it. Tried
                                once more and stopped rather than probing
                                for a form that slips through; a denial
                                is an answer.

                                Everything is staged: `git diff --cached
                                --stat` shows 158 files, +16738/-276, and
                                that is precisely the tree every gate
                                above was run against. The commit message
                                is written and waiting at
                                `.git/PHASE28_MSG.txt`, so the remaining
                                step is one command:

                                    git commit -F .git/PHASE28_MSG.txt

                                §2 is the architecture session's to write,
                                so I have not amended the 2026-09-09
                                decision that `-F` "matches the allow rule
                                cleanly" — but it does not, and after four
                                phases that is worth deciding rather than
                                rediscovering.
  Merged to main                NOT DONE, deliberately — the human review
                                checkpoint this whole protocol exists for.

Field 17 ("do NOT implement yet") — RESPECTED, verified by execution:
  no comparison and no divergences (grep across cli/, extractors/,
  api/app: `divergence` appears only in Phase 26's dormant table and its
  model); no network access of any kind from the CLI (no net/http import
  in cli/ at all — `culprit intent` reads files and runs subprocesses);
  no environment capture (`ExtractorRequest.environment` is always null
  and POST /facts/captures refuses a CONFIGURED bundle by name); no
  probes. `culprit intent` prints an inventory and stops.

Built:
  - cli/ — a Go module, 3,458 non-test lines (D2's revisit trigger is
    ~6k by end of Phase 29). internal/model/ mirrors culprit_model;
    internal/extract/ has the orchestrator, the subprocess plugin runner
    and five built-in artefact readers (OpenAPI/Swagger, .env.example,
    compose, Alembic version chains, seven dependency-manifest formats);
    internal/render/ prints text or JSON. No tree-sitter — see
    corrections.
  - shared/culprit_model/shape.py — the Q5 remediation. A closed
    ValueShape (type/length_class/format/present), mirrored in Go and
    JavaScript, plus protocol.py (the extractor contract and the capture
    bundle) and the Fact rules that enforce it.
  - extractors/python/ — FastAPI/Flask/Django route tables via runtime
    introspection, SQLAlchemy metadata, the Alembic head via Alembic
    itself, os.environ read sites and test status-code assertions by AST.
  - extractors/node/ — Express/Fastify/Koa route definitions, fetch/axios
    call sites, package.json, via @babel/parser.
  - api/app/facts/ — POST /facts/captures behind a project token, on a
    new fact-writer role (INSERT on captures/intent_facts, SELECT on
    captures, nothing on the other planes' tables).
  - api/app/errors.py — a 422 that does not echo the request body.
  - migration d1f4a9c73b60 — narrows configured_facts.value_shape to the
    closed form, gives intent_facts the same columns and constraints,
    creates fact-writer.
  - cli/testdata/fixtures/ — four projects, two vendored verbatim from
    pallets/flask (3.1.0) and expressjs/express (4.21.2) with their
    licences, plus golden files.
  - culprit.yaml at the repo root, describing Culprit to itself.
  - docs/EXTRACTOR_PROTOCOL.md, scripts/install.sh,
    .github/workflows/cli-release.yml, a `cli` CI job, ten just recipes.

Plan corrections — things the brief could not have known:
  1. FIELD 11 CONTRADICTS D3, AND go-tree-sitter WOULD BREAK CRITERION 5.
     Field 11 gives the Go binary "stdlib plus go-tree-sitter and cobra".
     D3 says the binary "never parses application code itself", which is
     the only thing tree-sitter would be for; and the Go binding needs
     cgo, which would end "one static binary" and the whole `curl | sh`
     story. The CLI uses stdlib + cobra + yaml.v3. Parsing stays in the
     extractors, where field 11 also puts it.
  2. THE NODE EXTRACTOR USES @babel/parser, NOT tree-sitter. The npm
     tree-sitter binding is a node-gyp native build — a compiler
     toolchain requirement in exactly the projects least likely to have
     one — and web-tree-sitter needs compiled .wasm grammars shipped
     alongside. @babel/parser is pure JS, ~2 MB, and reads .js/.jsx/.ts/
     .tsx with one call.
  3. FIELD 7's REQUEST SHAPE NEEDS A `component`. Every subject URI needs
     a component name and an extractor cannot invent one that will match
     the system model. Added to ExtractorRequest.
  4. FIELD 7's FIVE `want` VALUES HAVE NO HOME FOR DEPENDENCY VERSIONS,
     which criterion 1 requires. Added `dependencies` as a sixth rather
     than folding it into `db_schema`.
  5. CRITERION 2 IS UNSATISFIABLE AS LITERALLY WORDED without a pinned
     clock, because a capture legitimately records when it was taken.
     Rather than reinterpret the criterion, the CLI now honours
     SOURCE_DATE_EPOCH so it is literally checkable at a terminal.
  6. FIELD 15's "published binaries and packages" cannot be done from a
     session — see Definition of done.

Found and fixed en route — each caught by execution, not review:
  - THE FIXTURE CORPUS EARNED ITS KEEP IMMEDIATELY. The Flask tutorial
    configures itself with app.config.from_mapping and never touches
    os.environ, so the config-key reader — which works perfectly against
    everything in this repo — found nothing in it. A corpus of
    self-written fixtures would have reported that reader complete.
  - A DEPENDENCY PARSER TRUNCATING ITS OWN INPUT. `sqlalchemy[asyncio]>=2.0`
    ended the pyproject dependency array at the `]` of its extras marker,
    silently dropping every dependency after it — two of four, one
    mangled. The symptom, a short dependency list, is indistinguishable
    from a project with few dependencies.
  - EVERY FACT ATTRIBUTED TO EVERY COMPONENT. A component with no
    declared root defaulted to the manifest directory, so each reader ran
    once per component over the same tree and a database with no source
    was credited with the API's routes and Alembic head. Undeclared
    components are now skipped by name.
  - A SUBJECT RULE THAT DROPPED MOST REAL DEPENDENCIES. `/` was forbidden
    in the `dependency` part, which silently discarded every scoped npm
    package and every Go module path (15 of 35 in this repo's frontend).
    A dep subject splits on its *first* `/`, so `dep:web/@babel/parser`
    round-trips exactly. Relaxed in all three implementations with
    fixture cases pinning both round trips.
  - PLUGIN CLOCKS BREAKING CRITERION 2. Each extractor stamped its own
    wall clock and the orchestrator only overwrote an empty one, so two
    runs differed in every plugin-supplied fact. `captured_at` belongs to
    the capture, like `capture_id`; it is overwritten unconditionally now.
  - A CAPTURE WITH NO FACTS WAS UNPARSEABLE BY THE CONTROL PLANE. Go's
    nil slice marshals to `null`, and `CaptureBundle.facts` is a list —
    so the honest "no extractor installed, found nothing" capture would
    have been rejected 422 by the one endpoint that exists to receive it.
    Found by a new test validating a real golden bundle against the
    pydantic model; that Go/Python wire contract had nothing asserting it
    before.
  - A CHECK CONSTRAINT THAT LET A MISSING KEY THROUGH. `value_shape->>'type'
    IN (...)` is NULL when the key is absent, and a CHECK treats NULL as
    satisfied — so a shape missing any of the four fields passed. All four
    are COALESCE'd now and each has its own test.
  - MY OWN MUTATION TEST OF THE SCAN-COVERAGE GATE STAYED GREEN. Removing
    extractors/python from `just lint` did not turn it red, because a
    redundant `extractors-lint` recipe I had added was also parsed for
    ruff roots and covered for it. The coverage gate was measuring a
    command that was not the gate — invariant 9's own failure mode, one
    level up. Both redundant recipes deleted; the mutation now goes red.
  - THE GOLDEN FILES WERE NOT VALID CAPTURES. Golden normalisation
    rewrote the bundle's capture id for cross-machine stability but left
    every fact pointing at the real one, so the committed files were
    internally inconsistent and POST /facts/captures refused them — a
    record of "real CLI output" that could not be replayed. Found by a
    new end-to-end test that posts those very files through the real
    endpoint under the real role, which is the only test exercising the
    whole contract rather than a Python-shaped approximation of it.
  - THE OUTPUT CAP DID NOT CAP ANYTHING. `maxPluginOutput` was checked
    after reading everything into a bytes.Buffer, so a runaway extractor
    had already allocated the memory the cap exists to prevent. A bounded
    writer now refuses the excess, with the limit made injectable so the
    path is actually tested.

From the invariant audit (3 violations, 8 risks — all addressed):
  V1 THE GO HALF OF THE DETERMINISM GATE WAS TRIVIALLY EVADABLE. An
     aliased import inside a gofmt `import ( ... )` block — the canonical
     form — starts with an identifier, not `import`, and my
     "is this line import-shaped?" narrowing skipped it. The audit
     demonstrated it passing. Three current SDKs were missing from the
     list including github.com/google/generative-ai-go, the Gemini Go
     SDK, when LLM_PROVIDER=gemini is this repo's production default.
     And cli/cmd/ was covered by no root at all. Go is scanned line for
     line now (an import path can only be a quoted string); the list is
     broader; the root is `cli`. All three evasions are pinned as tests,
     and all three were mutation-tested red before and after.
  V2 POST /facts/captures STORED A CONFIGURED FACT AS AN INTENT FACT.
     The bundle's plane was checked; its facts' planes were not.
     `intent_facts` has no plane and no environment column, so a
     production DSN with a valid grant landed there with the plane, the
     environment and the grant all discarded — in a table with no
     grant_ref column and no grant constraint. Verified end to end
     against a real database under the real role. CaptureBundle now
     refuses a plane or environment mismatch, at request validation, so
     no code path routes around it.
  V3 value_shape WAS SILENTLY DISCARDED ON UPLOAD. Half the config facts
     a capture produces are shape-only, and `intent_facts` had no column
     for them: they stored as value=NULL while the response reported them
     saved. intent_facts gains value_shape and grant_ref with the same
     three constraints configured_facts carries — which matters more
     there, since it is the table an unattended CI credential can write.
  Risks, all fixed: the false describeValue comment; the Node extractor
     dropping facts silently on a subject error; the Python manifest
     loader not matching the Go one despite saying it did, and dropping
     an all-default extract entry on export; no 409 on a duplicate
     capture (a client-chosen, content-derived id means a CI retry posts
     the same one — it 500'd); `just lint` not covering Go; a stale
     filename in a comment. The upgrade path was documented in
     docs/UPGRADING.md before the audit raised it.

Found while fixing the audit's findings:
  - A 422 ECHOED THE CREDENTIAL IT HAD JUST REFUSED. FastAPI's default
    validation handler puts the offending value in the response, so
    refusing a bundle carrying a DSN wrote that DSN into this API's
    access log and the caller's CI log. Nothing is disclosed to a third
    party — the caller sent it — but holding extractors to "never carry a
    config value" while the error path publishes one is incoherent.
    api/app/errors.py strips `input` and `ctx` app-wide, keeping the
    field path and the message.
  - THE JSONB none_as_null TRAP, AGAIN. SQLAlchemy renders Python None as
    `'null'::jsonb`, and `'null'::jsonb IS NULL` is false — so every
    shape-less fact failed the new constraint. This is the same trap
    migration a3d81f6c4b27's docstring describes for `value`; the columns
    are declared `none_as_null=True` on both sides now.

From the SECOND invariant audit, run against the fixed tree (V1-V3
confirmed fixed; four new violations, all in code the fixes added — all
now fixed and each one tested):
  V4 `Fact.subject` WAS UNVALIDATED FREE TEXT. The check returned early
     when a subject did not parse, on the reasoning that `build()` owns
     that error — but nothing on this path calls `build()`: the wire
     carries a string and extractors are third-party subprocesses. The
     database's own check keys off an anchored, case-sensitive LIKE on
     the scheme, so it skipped these too. Both layers open at once: an
     upper-cased scheme and a leading space each stored a live DSN,
     ungranted, verified end to end. The subject must now round-trip
     through build(parse(s)) — free, since all 44 golden subjects
     already do.
  V5 A CONSTRAINT VIOLATION ESCAPED AS A 500 WITH THE ROW IN THE LOG.
     The insert sat outside the try, so a CHECK violation propagated
     uncaught — and Postgres's message carries `DETAIL: Failing row
     contains (...)`, which for a config fact is the value it refused.
     Exactly what api/app/errors.py exists to prevent, on a path it did
     not cover. Now a 422 naming the constraint's *rule* and nothing
     else.
  V6 THE DUPLICATE-CAPTURE 409 ONLY WORKED FOR AN EMPTY BUNDLE. Autoflush
     raises the primary-key violation at the insert, outside the try, so
     every real retry was a 500. Same one-line placement fix, plus
     discrimination on SQLSTATE 23505 so a CHECK failure is not reported
     as "already stored".
  V7 `btrim(x)` TRIMS SPACES ONLY. A `grant_ref` of "	
" satisfied the
     constraint while `Fact.strip()` refused it, so the docstring's claim
     that the two said the same thing was false. Now a `\s` regex.
  Risks fixed with them: the JS scan missed `.cjs` (the natural extension
     in a `"type": "module"` package) and four other suffixes; the
     scan-coverage *masking mechanism* was intact even after the
     offending recipe was deleted — `_ruff_roots` now parses only the
     `lint` recipe's body, and the auditor's two-step re-creation is
     mutation-tested red; `MismatchedCaptureId` echoed the subject, and
     now names the index.

Found while fixing those:
  - MY OWN FIX FOR V4 LEAKED. The new error messages quoted the offending
    subject — and `opaque:postgresql://u:hunter2@db/orders` is a perfectly
    good way to hide a DSN in one. Caught by the test written for the fix.
    No validation message echoes a subject, a value, or a canonical form
    derived from either; pydantic's `loc` names the fact instead.
  - THE CONSTRAINT NAME IS ON `orig.__cause__`, NOT `orig`. SQLAlchemy's
    asyncpg wrapper carries `sqlstate` but not `constraint_name`; the real
    asyncpg error underneath has both. Read only `orig` and every
    refusal fell back to a generic message — which is the entire reason
    that path exists rather than a 500. Verified against a live database.

Surfaced, deliberately NOT decided — wants an architecture call:
  - Q7: should ValueShape carry a `scheme`? The four fields were fixed by
    decision and implemented exactly; against real data the cost is now
    measurable — a DATABASE_URL pointing at postgresql in staging and
    mysql in production has the same shape. Wants deciding before Phase
    30 writes real CONFIGURED captures.
  - Q8: how should a user supply import-time environment for extraction?
    culprit.yaml correctly refuses credential-shaped values (it did,
    loudly, when placeholders were tried there), so `just intent` sets
    them — fine here, useless in a user's repo with no justfile. It is
    the first-impression problem for Phase 29.
  Neither blocks Phase 29.

From the phase audit (executed against the fixed tree):
  All five acceptance criteria MET — 1, 3 and 4 outright; 2 and 5 "in
  substance", with the deviations documented rather than hidden. Field 17
  clean, and checked decisively rather than by grep: `go list -deps
  ./cmd/culprit | grep -x net/http` returns nothing, so the binary
  contains no HTTP client at all.

  Field 15 NOT met, as above: nothing is published.

  Its judgement on criterion 2, which I agree with and did not prompt:
  honouring SOURCE_DATE_EPOCH is "a reinterpretation, not a literal
  satisfaction — but a defensible one, and the one I would have chosen",
  because dropping capture timestamps would make a bundle un-orderable
  and freezing the clock unconditionally would be a lie in the artefact.
  It asked that the plan's wording be brought into line rather than left
  to be rediscovered:

    "Two runs on an unchanged tree differ only in the capture's own
     timestamps and the capture_id derived from them; with
     SOURCE_DATE_EPOCH pinned the output is byte-identical."

  That is a change to docs/DIAGNOSTIC_PLAN.md's field 14 and therefore
  the architecture session's to make, not mine — raised here rather than
  applied.

  It also flagged, as low severity, that `str(pydantic.ValidationError)`
  renders the input it rejected. That turned out to matter more than
  "low": `culprit-extract-python` turns any failure into a `skipped`
  reason, and a skip travels *inside the capture bundle* — the artefact
  §5 promises is safe to attach to a bug report. Not reachable today
  (ValueShape is only ever built by of()/absent()/unknown(), none of
  which can put a value in a field), but one refactor away, and this
  guarantee is meant to be structural rather than "no current call site
  does it". `culprit_model.errors.safe_message` renders a validation
  failure without its input; the extractor uses it everywhere a failure
  becomes a reason. Pinned by a test that asserts *both* halves — that
  `str(exc)` does leak and that `safe_message` does not — so it cannot
  silently become a no-op if pydantic changes.

Also worth a decision, not raised as a question:
  - The frontend still has no test tooling (carried over from Phase 27).
  - Three copies of the DB role-password list, now four suites deep. No
    drift checker, unlike the ORM/Core pair. In docs/LIMITS.md.
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
