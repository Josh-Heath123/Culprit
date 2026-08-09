# Culprit — AI-Native Memory Plan (Phases 21–25)

Written 2026-08-08. Companion to `docs/SELF_HOSTED_PLAN.md` (Phases 13–20, all
built and deployed) — that document turned Culprit into something a third
party can self-host. This one is a different bet, built on top of that
foundation: Culprit becomes the memory of what happened to *this codebase* —
including what an AI coding agent did to it and what that caused in
production — made queryable by both a human and a coding agent, backed by a
small set of fast, deterministic checks that catch AI-introduced mistakes the
moment they're written instead of at review time.

**What this is not.** Not a general codebase-understanding platform, and not
an AI code reviewer competing with CodeRabbit/Sourcegraph/Greptile on their
own turf — this plan has no phase for a static-analysis codebase graph
(file/function nodes, import-edge parsing), and does not add one even as a
stretch goal; see Phase 25's Out-of-scope for why, and §1 invariant 7. The
differentiator is specifically the closed loop: an AI agent's change → what
it broke or caused (caught deterministically, or observed in production) →
that outcome becomes memory → future agent sessions get that memory as
context before making a similar change. Nothing else in this space owns both
the dev-time and the production-time side of that loop; that is the actual
bet this plan makes, not "our tools are individually better" than existing
point solutions.

---

## 0. How to use this document

Same convention as `docs/SELF_HOSTED_PLAN.md` §0 — each phase below is
written to be handed to a single Claude Code session with no other context
beyond `CLAUDE.md` and the repo itself. A phase section contains, in this
order: Goal, Depends on, Out of scope, Schema changes, API surface, Files
touched, Steps, Acceptance criteria, Tests, Rollback, Known traps.

**One phase per branch, one phase per PR.** Every phase below ends with a
green CI run as an acceptance criterion — CI already gates lint → typecheck
(+ `lint-imports` + `check-schema-drift`) → pytest → Trivy → push → deploy,
per `docs/SELF_HOSTED_PLAN.md` §0, and that gate does not relax here. Do not
stack two phases into one branch.

---

## 1. Invariants — true in every phase below

These extend, and do not replace, `docs/SELF_HOSTED_PLAN.md` §1's seven
invariants — all seven still apply verbatim (deterministic anomaly
detection and correlation, `worker`/`api` schema parity, least-privilege DB
roles, migrations as historical snapshots, secrets never in CI, the
`CLAUDE.md` scope ceilings, never dumping raw telemetry into context). This
plan adds:

8. **Every deterministic check this plan adds (Phase 22) stays deterministic
   and non-LLM, for the same reason Phase 4/5's anomaly detection and
   correlation do** (`CLAUDE.md`'s "Where the AI must stay deterministic"
   section). A hook that asks an LLM "does this diff look okay?" is slower,
   costs tokens on every edit, and can hallucinate "looks fine" — exactly
   the failure mode that section already names. `worker/pyproject.toml`'s
   `[[tool.importlinter.contracts]]` gets a third contract in Phase 23
   (`app.memory` forbidden from importing `app.rag`) for the same
   structural reason the existing two exist: a lint config to silence is
   the wrong response to a change that needs this boundary crossed, not a
   config problem.
9. **Reuse the existing embedding/retrieval plumbing; do not build a second
   one.** `worker/app/rag/embeddings.py` (`embed_document`/`embed_query`,
   Voyage `voyage-4`, 1024 dims) and the cosine-distance pattern in
   `worker/app/rag/retrieval.py` are the one embedding/retrieval mechanism
   in this codebase. Phase 21 generalizes retrieval to query across three
   tables instead of one; it does not stand up a parallel embedding client,
   a different model, or a second vector column shape.
10. **New tables get explicit `GRANT`s for exactly the roles that need
    them, same as `docs/SELF_HOSTED_PLAN.md` invariant 3** — and prefer
    extending an existing role's grants over minting a new one when the new
    table is conceptually the same trust domain as an existing one (Phase
    21's `architecture_decisions`/`ai_change_records` extend
    `postmortem-writer`'s grants rather than each getting a dedicated role;
    Phase 24's read-only MCP access is a genuinely new trust domain and gets
    its own role). Don't widen `api-reader` or `postmortem-writer` to cover
    something a narrower role should own instead.
11. **This plan does not touch the RAG root-cause narrative's own prompt or
    grounding (`worker/app/rag/llm.py`, `prompts.py`, `job.py`).** Linking
    an incident to a recent AI change record (Phase 23) does not mean that
    link gets fed into the incident's root-cause narrative — that's a real,
    separate, future decision (whether/how to ground root-cause hypotheses
    in "this looks like it followed a recent AI change") deliberately left
    for a later phase, not silently included here. Every phase below that
    could be tempted to reach into `worker/app/rag/llm.py` or
    `worker/app/rag/job.py` must flag that back rather than do it.

---

## 2. Phase order and dependency graph

```
Phase 21  Engineering memory (generalizes Phase 18's postmortem plumbing)
   │
   ├── Phase 22  Continuous, deterministic verification   (independent of 21)
   │        │
   │        └── Phase 23  Wire the flywheel  (needs both 21 and 22)
   │                 │
   │                 ├── Phase 24  Expose the memory via MCP
   │                 │
   │                 └── Phase 25  Scoped visualization
```

**This plan depends on Phase 18 (postmortem plumbing to generalize) and
Phase 16 (multi-user auth — `author_user_id` needs a real `users` table and
`require_auth`) being merged. It does not depend on Phase 19 (topology
inference) or Phase 20 (release engineering) completing first** — nothing
here touches trace ingestion, image tagging, or the repo/product naming
Phase 20 settled. Phases 13–20 are all merged as of this writing, so this is
academic for *when* work on this plan can start, but it matters for
understanding *why* the plan is written this way: it was designed against
the Phase 18/16 shape specifically, not against anything Phase 19/20 added.

**Phase 22 is independent of Phase 21** — a deterministic-check hook that
blocks a bad edit doesn't need anywhere to write a memory record until
something wants to persist that violation. Build them in either order, or in
parallel; Phase 23 is what makes them need each other.

**A real correction to how this was described going in:** Phase 25
(visualization) was framed as depending on "the same data Phase 24 exposes
to agents" — worded that way, it reads as depending on Phase 24 itself.
It doesn't. Both Phase 24 (MCP tools for an agent) and Phase 25 (routes for
a human) are independent consumers of the exact same Phase 21+23 data
(engineering records, violations, incident links) — neither one produces
data the other needs. **Phase 25 depends on Phase 21 and Phase 23, not on
Phase 24**, and the two can be built in either order or in parallel. The
dependency graph above reflects this correction; do not read Phase 24 as a
prerequisite for Phase 25 anywhere else in this document.

---

## Phase 21 — Engineering memory

### Goal

Generalize the existing `postmortems` table and write path (Phase 18) into a
small family of engineering records: postmortems (unchanged, already
exists), architecture decisions (new — same shape: title, body, embedding,
author, timestamps), and AI change records (new — one written automatically
per commit made inside a Claude Code session, capturing what changed, the
stated task/intent, which files, and when). Retrieval generalizes to search
across all three. The central risk this phase is designed against is the
cold-start problem: a memory system that requires a human to remember to
fill it out will sit empty and be worthless. Architecture decisions are
still human-written (like postmortems); AI change records are not — they
must fill themselves as a byproduct of normal commits, or this phase has
failed at its actual goal regardless of what else it builds.

### Depends on

Phase 18 (the postmortem write path this generalizes — same embedding
plumbing, same `postmortem-writer` role, same event-driven arq job pattern)
and Phase 16 (`users` table and `require_auth` for `author_user_id` and
gating the human-facing endpoints).

### Out of scope

- **Restructuring the existing `postmortems` table into a unified
  `engineering_records` table with a type discriminator.** `postmortems` is
  live, has real data, a real write path, frontend routes, and an embed job
  already. Merging it into a new shape for a "family of records" concept
  that's equally well served by three sibling tables is unnecessary risk to
  a working system for no functional gain — see Known Trap 1.
- **Feeding AI change records or architecture decisions into the root-cause
  narrative's grounding** (`worker/app/rag/llm.py`, `context.py`,
  `job.py`). Per invariant 11, that's a real, separate, future decision.
  This phase only makes the records exist and be retrievable by *something*
  that asks for them (Phase 24 is the first thing that actually asks).
- **Classifying AI change records by which agent/model made them**, or
  supporting agents other than Claude Code. The capture mechanism (Steps,
  below) is a Claude Code hook specifically; a record for a commit made
  by a human directly with `git commit`, or by a different AI tool, is not
  created. Generalizing the capture mechanism to other tools is future
  work, not this phase.
- **Automatically resolving `git_author` to a Culprit `author_user_id`** by
  matching git email to a registered user's email. `ai_change_records.
  author_user_id` stays `NULL` for hook-created records (see Schema
  changes) — a nice-to-have correlation, not required for this phase's
  acceptance criteria.
- **A UI for browsing or writing architecture decisions or AI change
  records.** That's Phase 25. This phase's API is complete and testable via
  `curl`/pytest without a frontend route existing yet.

### Schema changes

New migration, revising from the current head (`e6b6bd0e99df` as of this
writing — confirm with `alembic heads` before writing the actual migration,
per `docs/SELF_HOSTED_PLAN.md`'s own "the plan may have moved" caveat).

```sql
CREATE TABLE architecture_decisions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              TEXT NOT NULL,
    body               TEXT NOT NULL,
    embedding          VECTOR(1024),                 -- nullable, same reasoning as postmortems.embedding
    author_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ,
    embedded_at        TIMESTAMPTZ,
    embedding_error    TEXT
);

CREATE TABLE ai_change_records (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    commit_sha         TEXT NOT NULL UNIQUE,          -- one record per commit; re-running the hook on the same commit is a no-op, not a duplicate
    summary            TEXT NOT NULL,                 -- the commit message body -- the "stated task/intent" this phase can actually capture automatically
    files_changed      JSONB NOT NULL DEFAULT '[]'::jsonb,  -- list[str] of paths touched, from `git show --stat`
    git_author         TEXT,                          -- raw `git log --format=%an <%ae>` -- always present, since every commit has one
    author_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,  -- NULL for hook-created records; see Out of scope
    embedding          VECTOR(1024),
    committed_at       TIMESTAMPTZ NOT NULL,           -- the commit's own author date, not when this row was inserted
    created_at         TIMESTAMPTZ DEFAULT now(),
    embedded_at        TIMESTAMPTZ,
    embedding_error    TEXT
);
CREATE INDEX ix_ai_change_records_committed_at ON ai_change_records (committed_at);
```

`commit_sha UNIQUE` is the idempotency guard for Step 4's hook — a commit
amended or the hook re-run for any reason must not duplicate the row; the
write path is an upsert (`INSERT ... ON CONFLICT (commit_sha) DO NOTHING`
is enough, since a commit's own metadata never changes after the fact except
via `git commit --amend`, which produces a new SHA anyway).

Grants, in the same migration — extends `postmortem-writer`'s existing
grants rather than minting a new role (invariant 10):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON architecture_decisions TO "postmortem-writer";
GRANT SELECT, INSERT, UPDATE ON ai_change_records TO "postmortem-writer";  -- no DELETE: a change record is a fact about history, not user-editable content
GRANT SELECT ON architecture_decisions, ai_change_records TO "api-reader";
```

`api-reader` needs `SELECT` on both because, exactly like `postmortems`,
`GET` endpoints run on `api-reader` while writes run on `postmortem-writer`
— see `api/app/postmortems/router.py`'s own `get_read_session`/
`get_write_session` split, which Phase 21's new routers copy exactly.

### API surface

New Pydantic models and endpoints, mirroring `api/app/postmortems/`'s exact
shape (`schemas.py`, `service.py`, `router.py`, `config.py` per-package
convention):

```
GET    /architecture-decisions?limit=&offset=   -> paginated, body truncated in list view (same LIST_BODY_TRUNCATE_CHARS=280 convention)
POST   /architecture-decisions <- {"title", "body"}                     -> 201 ArchitectureDecisionOut
GET    /architecture-decisions/{id}                                     -> ArchitectureDecisionOut
PATCH  /architecture-decisions/{id} <- {"title"?, "body"?}               -> ArchitectureDecisionOut
DELETE /architecture-decisions/{id}                                     -> 204

GET    /ai-change-records?limit=&offset=&since=  -> paginated; `since` (ISO datetime, optional) filters committed_at >= since, for Phase 25's timeline view
GET    /ai-change-records/{id}                                          -> AiChangeRecordOut
POST   /ai-change-records <- {"commit_sha", "summary", "files_changed", "git_author", "committed_at"}
                                                                          -> 201 AiChangeRecordOut, or 200 if commit_sha already existed (no-op)
```

No `PATCH`/`DELETE` on `ai_change_records` — a change record describes what
actually happened; it isn't user-editable content the way a postmortem or
decision is.

`POST /architecture-decisions` and its `PATCH`/`DELETE` are gated by the
same `require_auth` every authenticated team member already has for
postmortems — not admin-only, matching `api/app/postmortems/router.py`'s
own docstring reasoning.

`POST /ai-change-records` is gated by a **new** dependency,
`require_auth_or_agent`, accepting *either* a valid user JWT (so a human
could, in principle, POST one by hand — not the primary path, but no reason
to forbid it) *or* a new bearer credential, `AGENT_AUTOMATION_TOKEN`
(env var, generated once by `scripts/bootstrap_env.py` alongside every other
generated secret — see Files touched). This is the one new auth surface in
this phase; every other endpoint reuses `require_auth` unchanged. Compare
this token against the stored value with `hmac.compare_digest`, the same
constant-time-comparison discipline `api/app/ingest_gateway/auth.py`
already uses for API keys — a timing side-channel on a single shared
automation token is a real, not theoretical, risk since it's long-lived and
never rotated per-request the way a user's short-lived JWT is.

`AiChangeRecordOut` never includes the raw embedding vector — same
`embedding_status` derivation (`pending`/`embedded`/`failed`) as
`PostmortemOut`, copied verbatim from `api/app/postmortems/service.py`'s
`_embedding_status`.

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_engineering_memory.py` | NEW |
| `api/app/db/models.py` | EDIT — `ArchitectureDecision`, `AiChangeRecord` |
| `worker/app/db.py` | EDIT — mirror both tables (worker only needs the columns `embed_job.py` writes: `embedding`, `embedded_at`, `embedding_error`, plus `id`/`body`/`summary` for reads — same "only enough shape" principle `worker/app/db.py`'s own docstring states) |
| `api/app/memory/__init__.py`, `schemas.py`, `service.py`, `router.py`, `config.py` | NEW — mirrors `api/app/postmortems/`'s package shape exactly; both `architecture_decisions` and `ai_change_records` live in this one package (small enough that splitting further would just be indirection, same reasoning `api/app/postmortems/service.py`'s own docstring gives for not having a separate `transforms.py`) |
| `api/app/auth/dependencies.py` | EDIT — `require_auth_or_agent` |
| `api/app/main.py` | EDIT — mount the new router (reuses the existing `postmortem_session_factory`/`session_factory` engines already in `app.state`; no new engine) |
| `worker/app/rag/embed_job.py` | EDIT — extract the shared rate-limit/retry/write logic `embed_postmortem` already has into `_embed_record(engine, table, record_id, text, ...)`, add `embed_architecture_decision`/`embed_ai_change_record` as thin wrappers calling it; `embed_postmortem` itself becomes a thin wrapper too, behavior unchanged |
| `worker/app/rag/retrieval.py` | EDIT — add `retrieve_similar_records(conn, query_embedding, top_k, record_types)` (a `UNION ALL` across the three tables); leave `retrieve_similar_postmortems` in place, unchanged, since `worker/app/rag/job.py`'s existing root-cause grounding still calls it and this phase doesn't touch that job (invariant 11) |
| `worker/app/main.py` | EDIT — register `embed_architecture_decision`/`embed_ai_change_record` in `WorkerSettings.functions` |
| `.claude/hooks/capture_ai_change.sh` | NEW — the auto-capture hook, see Steps |
| `.claude/settings.json` | NEW (doesn't exist yet in this repo — confirmed via `ls .claude/`) — declares the `PostToolUse` hook wiring |
| `scripts/bootstrap_env.py` | EDIT — generate `AGENT_AUTOMATION_TOKEN` alongside every other secret (`GENERATED_SECRETS` list) |
| `infra/.env.prod.example` | EDIT — `AGENT_AUTOMATION_TOKEN` |

### Steps

1. Migration first. `just check-schema-drift` before writing anything else,
   per `docs/SELF_HOSTED_PLAN.md`'s own established discipline.
2. Build `api/app/memory/` for `architecture_decisions` — this is a direct
   copy-and-adapt of `api/app/postmortems/`, so do this first as the
   template the `ai_change_records` half follows.
3. Add `ai_change_records`' endpoints in the same package. `require_auth_or_
   agent` in `api/app/auth/dependencies.py`: check for
   `Authorization: Bearer <AGENT_AUTOMATION_TOKEN>` first (constant-time
   compare); fall through to the existing `require_auth` JWT path if that
   header doesn't match. Both paths converge on the same handler; the
   handler receives `author_user_id: UUID | None` (`None` for the agent
   path).
4. **The capture hook** (`.claude/hooks/capture_ai_change.sh`), the actual
   point of this phase. A `PostToolUse` hook matching `Bash`, verified
   against Claude Code's current hooks documentation (exit code 2 blocks
   and returns stderr to the agent; the hook receives JSON on stdin with
   `tool_name`/`tool_input.command`; declared in `.claude/settings.json`
   under `hooks.PostToolUse` with a `matcher` and a `command` pointing at
   this script). The script:
   - Reads stdin, checks whether `tool_input.command` contains `git commit`
     (a plain substring check is enough — false positives on e.g. `git log
     --grep "git commit"` cost nothing, they just fail the "does HEAD's SHA
     already have a record" check harmlessly). Exit 0 immediately for any
     other command — this hook must be near-instant for every other `Bash`
     call, since it fires on all of them.
   - On a match: `git rev-parse HEAD` (the SHA just created), `git log -1
     --format=%B` (message/intent), `git show --stat --format= HEAD`
     (files changed), `git log -1 --format=%an <%ae>` (`git_author`),
     `git log -1 --format=%aI` (`committed_at`).
   - `POST /ai-change-records` with `AGENT_AUTOMATION_TOKEN` from the
     environment (sourced from `worker/.env`/`api/.env` locally, or
     `infra/.env.prod` in production — the hook needs read access to
     whichever env file is live in that context).
   - Never blocks or fails the commit itself: a failed POST (API down,
     network issue) logs to stderr and exits 0, not 2 — losing one memory
     record is a real but recoverable gap; blocking every commit on this
     endpoint's availability is a worse failure mode than the one this
     phase is trying to fix.
5. `scripts/bootstrap_env.py`: add `AGENT_AUTOMATION_TOKEN` to
   `GENERATED_SECRETS`, following the exact pattern the Phase 18 session
   used for `POSTMORTEM_WRITER_DB_PASSWORD` (`docs/SELF_HOSTED_PLAN.md`
   Phase 18's own migration required this env var; the equivalent gap for
   this phase is `bootstrap_env.py` never generating it and `just
   quickstart` breaking the moment the hook tries to authenticate with an
   unset token — don't repeat that specific, already-once-made mistake).

### Acceptance criteria

- A commit made through a Bash `git commit` call inside a Claude Code
  session produces exactly one `ai_change_records` row within a few
  seconds, with `summary` matching the commit message, `files_changed`
  matching `git show --stat`, and `embedding_status` reaching `"embedded"`
  without any manual step.
- A commit made directly by a human running `git commit` from a plain
  terminal (not inside a Claude Code session, so the hook never fires)
  produces no row — verified live, not assumed: this is the boundary Out
  of scope draws, and it must actually hold, not just be documented.
  (`docs/LIMITS.md` should gain a line about this once implemented — every
  commit outside a Claude Code session is invisible to this system.)
- A team writes an architecture decision through `POST
  /architecture-decisions`; within a minute `embedding_status` is
  `"embedded"`, mirroring Phase 18's own postmortem acceptance criterion.
- `retrieve_similar_records` returns results from all three tables when
  called with the default `record_types`, and from only the requested
  subset when narrowed — verified with a query that has close matches in
  two of the three tables and confirming both, not just one, come back.
- `api-reader` cannot write to either new table (assert with a
  role-scoped connection in a test, same pattern
  `api/tests/test_postmortems_api.py::test_api_reader_cannot_write_to_
  postmortems` already establishes).
- A `POST /ai-change-records` with a `commit_sha` that already has a row
  returns 200 (not 201, not 409) and does not create a second row —
  re-running the hook (e.g. after a crash mid-request) must be safe.
- `just check-schema-drift`, `just lint-imports`, `just lint`, `just
  typecheck`, `just test` all pass; CI green.

### Tests

- `api/tests/test_memory_api.py` — CRUD for architecture decisions
  (mirroring `test_postmortems_api.py` closely), `ai_change_records`
  create/idempotent-recreate/list-with-`since`-filter, `require_auth_or_
  agent` accepting both a valid JWT and a valid automation token and
  rejecting neither/wrong-token, `api-reader` write rejection for both
  tables, no-embedding-vector-in-response for both.
- `worker/tests/test_embed_job.py` — EDIT to also cover
  `embed_architecture_decision`/`embed_ai_change_record` against the
  refactored shared helper; the existing `embed_postmortem` test cases
  must keep passing unchanged, proving the refactor didn't change its
  behavior.
- `worker/tests/test_rag_retrieval.py` — NEW (no such file exists yet;
  `retrieval.py` has no direct test today) — `retrieve_similar_records`
  across tables, `record_types` filtering, `embedding IS NOT NULL` still
  excludes pending rows the same way `retrieve_similar_postmortems`
  already does.
- The hook itself: a shell-level test invoking
  `.claude/hooks/capture_ai_change.sh` with a synthetic stdin JSON payload
  and a real (test) git repo, asserting the correct API call shape without
  needing a live Claude Code session — the live-session behavior is the
  "verified live" acceptance criterion above, not something a unit test
  can cover.

### Rollback

The migration's `downgrade()` drops both tables and revokes
`postmortem-writer`'s new grants (its existing `postmortems` grants are
untouched — this migration only revokes what it itself granted, matching
every prior phase's own downgrade discipline). Removing `.claude/
settings.json`'s hook entry is a pure config revert with no data
implication — a rolled-back deploy simply stops creating new records; every
existing one survives. No existing data is lost either way.

### Known traps

- **Trap 1.** The temptation here is to treat "generalize into a family of
  records" as license to restructure `postmortems` itself into a generic
  table. Don't — see Out of scope. The three tables share a *retrieval*
  interface (Step 6's `UNION ALL`), not a *storage* schema, and that's a
  deliberate, not a lazy, choice: `postmortems` already has a working write
  path, a frontend, and real user data; touching its schema for a
  refactor with zero new capability is exactly the kind of risk this
  project's own migration discipline (invariant 4, "migrations are
  historical snapshots") exists to avoid inviting.
- **Trap 2.** `AGENT_AUTOMATION_TOKEN` is a single, long-lived, unrotated
  shared secret — closer to `INGEST_GATEWAY_DATABASE_URL` than to a
  per-user JWT. Log its *presence*, never its value, on auth failure (same
  discipline `docs/SELF_HOSTED_PLAN.md` Phase 15 established for API-key
  prefixes) — a stack trace or debug log that includes the raw token
  defeats the entire point of it being a secret.
- **Trap 3.** The hook fires on *every* `Bash` tool call, not just git
  commits — it must exit near-instantly for the common case (not a `git
  commit`) or it measurably slows down every single shell command in every
  Claude Code session using this repo. Do the substring check on `tool_
  input.command` first, before any subprocess spawn, before any network
  call.
- **Trap 4.** `commit_sha` uniqueness matters more than it looks: a
  network retry, a hook re-fire, or a user re-running `git commit --amend`
  and then un-amending (rare, but the SHA is genuinely different each
  time) must not silently create duplicate or orphaned rows.
  `ON CONFLICT (commit_sha) DO NOTHING` handles the exact-SHA-retry case;
  an amended commit is, correctly, a *new* row with a *new* SHA, not an
  update to the old one — the old row still accurately describes the
  commit that used to exist at that SHA.
- **Trap 5.** `worker/app/rag/embed_job.py`'s refactor (Step 4/Files
  touched) is the one place in this phase touching already-shipped,
  already-tested code. Extract the shared helper *without* changing
  `embed_postmortem`'s observable behavior — the existing
  `worker/tests/test_embed_job.py` suite is the regression guard; if any
  of those tests need to change to pass, the refactor changed behavior it
  shouldn't have.

---

## Phase 22 — Continuous, deterministic verification

### Goal

Generalize `scripts/check_schema_drift.py`'s exact pattern — a fast,
non-LLM script that diffs two declared-coupled things and fails loudly on
mismatch — into a small registry of exactly two invariants, checked the
moment a file is written (via a Claude Code hook), not just later in CI:

1. A migration's `upgrade()`/`downgrade()` must be structurally symmetric.
2. A declared "these files must change together" pairing (generalizing the
   `worker/app/db.py` ↔ `api/app/db/models.py` relationship
   `check_schema_drift.py` already encodes as one hardcoded case into an
   arbitrary, declarable list).

### Depends on

Nothing in this plan — see §2. Depends on the existing CI structure
(`.github/workflows/ci-cd.yml`'s `typecheck` job, where `just
check-schema-drift` already runs) only in the sense that this phase's new
checks are wired into the same job, not a new one.

### Out of scope

- **Any invariant beyond the two named above.** This phase proves the
  mechanism (a registry + a hook + a CI step) works for a small,
  concretely-specified set; adding a third, fourth, or Nth invariant is a
  future phase's problem once this one has real usage behind it, not a
  reason to design a more elaborate rules engine now than two checks
  justify.
- **An LLM reviewing the diff for "does this look like a good change."**
  Invariant 8 forbids this outright, not as a style preference.
- **Auto-fixing a violation.** The hook blocks and explains; it does not
  edit the file back into compliance. An agent that reads the blocked
  reason and fixes it itself is the intended flow, not a script guessing
  at the fix.
- **Persisting violations anywhere.** That's Phase 23's `invariant_
  violations` table. This phase's hook blocks in real time and prints to
  stderr; it does not write to a database. (The CI-time version of the
  same check, Step 5, also just fails the build — same reasoning.)

### Schema changes

None. This phase is pure code — a script, a hook, and a CI step. No new
table, no migration, no DB role.

### API surface

None. This phase adds no HTTP endpoint.

### Files touched

| Path | Action |
| --- | --- |
| `scripts/check_migration_symmetry.py` | NEW |
| `scripts/coupled_files.yaml` | NEW — the declarable "must change together" registry |
| `scripts/check_coupled_files.py` | NEW |
| `.claude/hooks/check_invariants.sh` | NEW — the `PostToolUse` hook wrapper calling both scripts |
| `.claude/settings.json` | EDIT (created by Phase 21 if that phase landed first; created here otherwise) — adds this phase's `PostToolUse` entry alongside Phase 21's, if both exist |
| `.github/workflows/ci-cd.yml` | EDIT — two new steps in the `typecheck` job, alongside the existing `check-schema-drift` step |
| `justfile` | EDIT — `just check-invariants` running both scripts, matching `just check-schema-drift`'s own convention |

### Steps

1. **`scripts/check_migration_symmetry.py`** — takes a migration file path
   (or, with no argument, every file changed vs. `main` per `git diff
   --name-only main...HEAD -- api/migrations/versions/`), parses its
   `upgrade()`/`downgrade()` function bodies with Python's `ast` module
   (no `alembic`/DB connection needed — purely static), and extracts the
   set of `op.<verb>(...)` calls in each. Assert structural symmetry:
   every `create_table("x")` in `upgrade` has a `drop_table("x")` in
   `downgrade`; every `add_column("t", "c")` has a `drop_column("t", "c")`;
   every `execute(...)` containing `GRANT ... TO "{role}"` has a
   corresponding `REVOKE`/`DROP ROLE` pattern for that role in `downgrade`.
   This is deliberately structural, not semantic — it cannot verify a
   `downgrade()` actually *works* (only a real `alembic downgrade` run
   proves that, which is why every phase in `docs/SELF_HOSTED_PLAN.md`
   still lists that as a manual Rollback verification step); it catches
   the much more common mistake of a migration author forgetting the
   downgrade half entirely, or misnaming a table/column between the two
   functions.
2. **`scripts/coupled_files.yaml`** — a flat list of path pairs:
   ```yaml
   pairs:
     - [worker/app/db.py, api/app/db/models.py]
   ```
   Seeded with exactly the one pairing `check_schema_drift.py` already
   encodes — this phase's job is to make that relationship *declarable*
   for future pairs, not to invent new pairs speculatively. `scripts/
   check_coupled_files.py` reads this file, takes the current `git diff
   --name-only` (staged + unstaged, matching what a `PostToolUse` hook can
   actually see at edit time — not just `main...HEAD`, since the hook must
   catch this mid-session, before any commit exists yet), and for every
   pair where exactly one side appears in that diff, reports a violation.
3. **`.claude/hooks/check_invariants.sh`** — `PostToolUse`, matcher
   `"Edit|Write"`. Runs `check_coupled_files.py` on every fire (cheap: one
   `git diff --name-only` plus a small YAML read); runs `check_migration_
   symmetry.py` only when the just-edited file (`tool_input.file_path`,
   from the hook's stdin JSON) is under `api/migrations/versions/` (no
   reason to parse migration ASTs on every unrelated edit). On any
   violation: exit code 2, message to stderr describing exactly which
   pairing or which migration function is out of sync — verified against
   Claude Code's current hooks documentation that exit 2 is what feeds
   stderr back to the agent as actionable context, not just a silent log
   entry (a hook that returns exit 1 fails "quietly," per that same
   documentation — the wrong exit code here means this phase looks like it
   works in manual testing and then silently doesn't in a real session).
4. CI: two new steps in `.github/workflows/ci-cd.yml`'s `typecheck` job,
   right after the existing `check-schema-drift` step — `check_coupled_
   files.py` run against `git diff --name-only origin/main...HEAD` instead
   of the working tree (CI has no uncommitted edits to look at), and
   `check_migration_symmetry.py` against every migration file changed in
   the same diff. This is the safety net for a commit that happened
   outside a hook-covered session (a human editing directly, or a hook
   that failed to fire) — the hook is real-time convenience, CI is the
   actual gate.
5. `just check-invariants` wraps both scripts for local, non-hook use
   (matching `just check-schema-drift`'s own existence as both a `just`
   recipe and a CI step).

### Acceptance criteria

- Editing `worker/app/db.py` alone (via the `Edit` tool, inside a Claude
  Code session with the hook installed) without touching `api/app/db/
  models.py` in the same working tree is blocked — verified live: the
  edit tool call itself surfaces the violation back to the agent, not
  just a later `just check-invariants` run.
- Editing *both* files in the same working tree — regardless of which one
  the hook fires on last — is not blocked.
- A migration file whose `downgrade()` is missing a `drop_table` for a
  table `upgrade()` creates is blocked on save, with a message naming the
  specific table.
- A migration file with a correctly symmetric `upgrade()`/`downgrade()` is
  never blocked, including every existing migration in `api/migrations/
  versions/` as of this phase's own merge — run `check_migration_
  symmetry.py` against every one of them as part of this phase's own
  verification and confirm zero false positives on real, already-shipped,
  correct migrations.
- The CI step fails a PR that removed `worker/app/db.py`'s mirror of a
  column without touching `api/app/db/models.py`, and passes one that
  changed both.
- Neither script, nor the hook script wrapping them, imports anything
  from an LLM/embedding client (`anthropic`, `voyageai`, `google.
  generativeai`, or this project's own `worker/app/rag/`) — assert this
  structurally (a test that greps the three new script files' imports),
  the same style of structural proof `lint-imports` already gives
  invariant 1, applied here to invariant 8.
- `just check-invariants`, `just lint`, `just typecheck`, `just test` all
  pass; CI green.

### Tests

- `scripts/tests/test_check_migration_symmetry.py` (or wherever this
  project's convention puts top-level script tests — check `scripts/`
  for precedent first; none of the existing scripts have tests today, so
  this phase sets that precedent) — symmetric migration passes,
  missing-`drop_table` fails with the right table name, missing-`REVOKE`
  fails, a migration with no grants at all (most of them) passes trivially.
- `scripts/tests/test_check_coupled_files.py` — both-changed passes,
  one-changed-only fails naming the missing side, neither-changed passes
  trivially, a pair not in `coupled_files.yaml` is never checked.
- The "no LLM import" structural test named in Acceptance criteria above.
- Hook-level: same shell-invocation-with-synthetic-stdin approach as
  Phase 21's own hook test — assert the correct exit code and stderr
  content without needing a live session for the automated part; live
  verification (the actual Edit-tool-gets-blocked behavior) is manual,
  same as every "verified live" criterion in `docs/SELF_HOSTED_PLAN.md`.

### Rollback

Pure code + config, no schema, no data. Revert the commit; `.claude/
settings.json`'s hook entries disappear and edits stop being checked
in real time, but nothing about already-written code changes, and CI's
own two new steps disappearing just means one less gate, not a broken one.

### Known traps

- **Trap 1.** `PostToolUse` fires *after* the tool already executed — per
  the verified hooks documentation, blocking here prevents the result from
  being used in the agent's next turn, but does **not** undo the file
  write. A blocked coupling violation leaves the just-edited file
  half-changed on disk; the agent's own next move (fix the paired file, or
  revert the one it just wrote) is what actually resolves it, not the hook
  itself. Don't design or document this as "the hook prevents the bad
  edit" — it doesn't; it surfaces the violation immediately after, which
  is the whole point (dev-time, not review-time) but is a real, worth-
  stating distinction from a `PreToolUse` hook that could actually refuse
  the write.
- **Trap 2.** The coupled-files check reads the *working tree's* diff
  state, not the specific edit that just happened. This is deliberate
  (Step 2) but easy to misdesign as "check if this specific edit's paired
  file changed in this specific tool call" — that would incorrectly block
  every edit to `worker/app/db.py` that comes *before* the matching edit
  to `api/app/db/models.py` in the same session, even when the agent's
  very next action is exactly that edit. Checking the whole diff state
  (both changed *somewhere* in the current uncommitted work) is what makes
  the ordering-agnostic acceptance criterion above true.
- **Trap 3.** `PostToolUse` hooks matching `Edit|Write` fire on *every*
  matching tool call across the whole session, including files this
  project's own conventions don't want checked at all (editing this very
  document, for instance, or any file under `docs/`). Both scripts must
  degrade to a fast no-op when the edited file isn't a migration and isn't
  one side of a declared pair — don't let hook latency become a reason
  someone disables it for the whole session.
- **Trap 4.** AST-based symmetry checking cannot see through indirection —
  a migration that builds its table/column names from a variable or an
  f-string with a non-literal argument (several existing migrations do
  exactly this for role names, e.g. `f'GRANT ... TO "{ROLE_NAME}"'` where
  `ROLE_NAME` is a module-level constant) needs the checker to resolve
  simple module-level string constants, not just literal string arguments.
  Verify this against the *actual* migrations in `api/migrations/versions/`
  before considering the checker done — several of them (`cc323b6c7779`,
  `635870479f4e`, `e6b6bd0e99df`) use exactly this pattern, and a checker
  that only handles literal strings will false-positive on all of them.

---

## Phase 23 — Wire the flywheel

### Goal

No new user-facing surface. This phase connects Phase 21 and Phase 22 to
each other, and both of them to the existing incident-correlation pipeline,
automatically — this is what makes the memory in Phase 21 actually fill
itself over time with the highest-value content (what broke, and what
change preceded it) instead of only ever containing what a human chose to
write by hand.

Two links, both rule-based, no LLM involved (invariant 8 continues to
apply — this phase is exactly as deterministic as Phase 4/5's anomaly
detection and correlation, not a judgment call):

1. Every Phase 22 invariant violation becomes a Phase 21 `ai_change_records`
   row (or is linked to the existing one for the same commit, if any).
2. Every incident the existing correlation engine (`worker/app/
   correlation/`) creates, if it falls within a short time window of a
   recent AI change record touching a related service, gets linked to
   that record.

### Depends on

Phase 21 (the `ai_change_records` table and its write path) and Phase 22
(the violation-detection mechanism this phase persists output from).

### Out of scope

- **Feeding these links into the root-cause narrative.** Invariant 11,
  restated because this is the phase most tempted to violate it — "this
  incident correlates with a change from 20 minutes ago" is exactly the
  kind of fact that feels like it belongs in the LLM prompt, and it may
  eventually, but that's a deliberate future decision about what
  `worker/app/rag/prompts.py` includes, not an automatic consequence of
  this phase existing.
- **Merging or deduplicating incidents based on shared AI-change
  ancestry.** `worker/app/correlation/`'s own merge-conflict handling
  (`docs/SELF_HOSTED_PLAN.md` invariant 1's domain) is untouched; this
  phase only *annotates* incidents that already exist with a link, it
  never changes which anomalies get grouped into which incident.
- **A configurable "short time window" or "related service" threshold**
  exposed anywhere. Both are fixed constants for this phase (see Steps) —
  making them admin-configurable is a reasonable future addition once
  there's real data showing the fixed values are wrong, not something to
  build speculatively now.

### Schema changes

New migration, revising from Phase 21's or Phase 22's head (whichever
merged last):

```sql
CREATE TABLE invariant_violations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invariant_name    TEXT NOT NULL,          -- "migration_symmetry" | "coupled_files"
    file_paths        JSONB NOT NULL,         -- list[str] -- the file(s) involved
    message           TEXT NOT NULL,          -- the hook's own violation message
    detected_at       TIMESTAMPTZ DEFAULT now(),
    ai_change_record_id UUID REFERENCES ai_change_records(id) ON DELETE SET NULL
);

CREATE TABLE incident_change_links (
    incident_id          UUID NOT NULL REFERENCES incident_candidates(id) ON DELETE CASCADE,
    ai_change_record_id  UUID NOT NULL REFERENCES ai_change_records(id) ON DELETE CASCADE,
    linked_at            TIMESTAMPTZ DEFAULT now(),
    link_reason          TEXT NOT NULL,       -- e.g. "order-service anomaly 14m after a change touching demo-services/order_service/main.py"
    PRIMARY KEY (incident_id, ai_change_record_id)
);
```

`invariant_violations.ai_change_record_id` is nullable and set only when a
violation is detected *after* a commit exists to attach it to (the CI-time
check, Step 2) — a hook-time violation (Phase 22 Step 3) blocks *before*
any commit happens, so there is no commit yet to link it to; see Known Trap
1.

Grants:

```sql
GRANT SELECT, INSERT ON invariant_violations TO "postmortem-writer";
GRANT SELECT, INSERT ON incident_change_links TO "correlation-engine";
GRANT SELECT ON invariant_violations, incident_change_links TO "api-reader";
```

`correlation-engine` (not `postmortem-writer`) gets the `incident_change_
links` grant because the *linking job* (Step 3) runs as part of `worker`'s
existing correlation-adjacent cron infrastructure, reusing that role's
existing read access to `incident_candidates`/`anomalies`, not a new
engine.

### API surface

No new endpoints. `GET /ai-change-records/{id}` (Phase 21) gains
`linked_incident_ids: list[UUID]` and `violations: list[InvariantViolationOut]`
in its response shape — a read-side addition to an existing schema, not a
new route. `GET /incidents/{id}` (`api/app/incidents/`, pre-existing) gains
`linked_ai_change_records: list[AiChangeRecordSummary]` the same way.

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_wire_the_flywheel.py` | NEW |
| `api/app/db/models.py`, `worker/app/db.py` | EDIT |
| `api/app/memory/schemas.py`, `service.py` | EDIT — the two response-shape additions above |
| `api/app/incidents/schemas.py`, `transforms.py` | EDIT — `linked_ai_change_records` |
| `worker/app/memory/__init__.py`, `link_job.py` | NEW — the linking cron job; a new top-level module, not inside `app.correlation` or `app.rag` (see Steps) |
| `worker/app/main.py` | EDIT — register `link_recent_changes` as a new cron job |
| `worker/pyproject.toml` | EDIT — third `[[tool.importlinter.contracts]]`: `app.memory` forbidden from importing `app.rag` (invariant 8) |
| `.claude/hooks/check_invariants.sh` (Phase 22) | EDIT — on a real violation, also `POST` to a new internal write path so the violation is persisted, not just printed |

### Steps

1. Migration, both `db` definitions, `just check-schema-drift`.
2. **Persisting violations.** Phase 22's hook (`.claude/hooks/check_
   invariants.sh`) already detects violations in real time but, per that
   phase's own Out-of-scope, doesn't persist them. This phase adds that:
   on a violation, the hook script also calls `POST /invariant-violations`
   (new endpoint, `require_auth_or_agent` reused from Phase 21) *in
   addition to* exiting 2 — the block still happens; persistence is a
   side effect, not a replacement for blocking. `ai_change_record_id`
   stays `NULL` here, since no commit exists yet at hook-fire time (Known
   Trap 1) — the CI-time check (Phase 22 Step 4) is what can attach a
   real commit, since by CI time a commit definitely exists.
3. **`worker/app/memory/link_job.py`** — a new arq cron job,
   `link_recent_changes`, running on the same 5-second-family cadence as
   `correlate_recent_anomalies` (staggered, per `worker/app/main.py`'s
   existing pattern — pick an unused second offset). For every
   `incident_candidates` row opened in the last cron tick's window, pull
   `ai_change_records` with `committed_at` within a fixed **30-minute**
   lookback of the incident's `opened_at` (a deliberately generous, fixed
   window — see Known Trap 2 for why this can't be precise), then apply a
   deliberately crude, honest heuristic: a change record is "related" if
   any of the incident's `anomalies.service_name` values appears as a
   substring of any path in that record's `files_changed` (matching, e.g.,
   `order-service` against `demo-services/order_service/main.py` requires
   normalizing hyphens to underscores first — services are named
   `order-service`, directories are `order_service`). Insert a
   `incident_change_links` row for every match, with `link_reason`
   recording which service/file pair triggered it.
4. **Module boundary.** `worker/app/memory/link_job.py` imports only from
   `app.db` (Core tables — `incident_candidates`, `anomalies`,
   `ai_change_records`, `incident_change_links`) and `app.observability`
   (`instrument_job`), exactly the way `worker/app/rag/context.py` already
   reads `incident_candidates`/`anomalies` without importing `app.
   correlation` — this job needs correlation's *output* (the DB rows), never
   its *code*. Add the third `importlinter` contract (Files touched) as a
   structural guarantee this stays true, matching the existing pair's own
   reasoning exactly.
5. Extend `api/app/memory/service.py`'s output builders and `api/app/
   incidents/transforms.py` to include the new linked-record/linked-
   incident lists — plain joins against the new tables, no new engine.

### Acceptance criteria

- A Phase 22 hook violation, fired inside a Claude Code session, produces
  an `invariant_violations` row within seconds (verified live via the
  API, not just the hook's own stderr).
- An incident whose anomalies are on `order-service`, opened 14 minutes
  after a commit touching `demo-services/order_service/main.py`, is
  linked to that commit's `ai_change_records` row within one
  `link_recent_changes` tick after the incident opens.
- An incident with no AI change record in the lookback window at all
  gets no link — verified as its own case, not just inferred from the
  positive case above (an empty result and a bug that silently links
  nothing look identical from the outside; the test must actually check
  for zero rows, not just "no error").
- An incident whose only recent change record touches an *unrelated*
  service is not linked — this is the actual discriminating test for the
  heuristic, mirroring how Phase 19's own acceptance criteria required
  proving the *negative* case (inventory→payments never proposed), not
  just the positive ones.
- Deleting an `ai_change_records` row (however that happens — this phase
  doesn't add a delete endpoint, but the FK's own `ON DELETE CASCADE`
  must still be correct) removes its `incident_change_links` rows without
  touching the `incident_candidates` row itself, same non-cascading-into-
  telemetry discipline `docs/SELF_HOSTED_PLAN.md` Phase 14's own service-
  deletion semantics established.
- `worker`'s `lint-imports` fails a change that makes `app.memory` import
  `app.rag`, and passes the actual shipped code.
- `just check-schema-drift`, `just lint-imports`, `just lint`, `just
  typecheck`, `just test` all pass; CI green.

### Tests

- `api/tests/test_memory_api.py` — EDIT to cover the new
  `linked_incident_ids`/`violations` response fields.
- `api/tests/test_incidents_transforms.py` — EDIT for `linked_ai_change_
  records`.
- `worker/tests/test_link_job.py` — NEW: the service-name-to-file-path
  heuristic (positive match, negative/unrelated-service case, hyphen/
  underscore normalization), the lookback window boundary (a change just
  inside 30 minutes links, just outside doesn't — an off-by-one here is
  exactly the kind of thing `docs/SELF_HOSTED_PLAN.md` Phase 19's own
  "exactly at window boundary" test in `test_correlation_graph.py` already
  had to get right for the analogous correlation-window logic).
- A structural test asserting `worker/app/memory/link_job.py` never
  imports `app.rag` or `app.correlation`, same style as Phase 22's own
  no-LLM-import structural test.

### Rollback

Both new tables' `downgrade()` drop them and revoke only what this
migration granted. Reverting the deploy stops new links/violations from
being created; every existing `incident_candidates`/`ai_change_records`
row is untouched either way, since neither new table is referenced by
anything else's foreign keys.

### Known traps

- **Trap 1.** A hook-time violation (Phase 22 Step 3) fires *before* the
  agent has committed anything — there is no `commit_sha` yet to attach
  the violation to. Don't design the write path to *require* an
  `ai_change_record_id` at insert time; it's nullable specifically because
  the two write paths (hook-time, pre-commit; CI-time, post-commit) have
  genuinely different information available. A violation that never gets
  a linked commit (because the agent fixed it and the fixed version was
  what actually got committed) is the *correct*, expected outcome for most
  hook-time violations — that's the system working, not a gap to backfill.
- **Trap 2.** The 30-minute lookback and the substring-based service/file
  match are both deliberately crude. A real incident caused by a change
  from an hour ago, or one whose service name doesn't appear anywhere in
  the changed file's path (a shared library file touched instead of the
  service's own directory, for instance), will not be linked. This is an
  honest, stated limitation (belongs in `docs/LIMITS.md` once
  implemented), not a bug to silently try to perfect — a heuristic that
  occasionally misses a real correlation is a far smaller problem than one
  that confidently links unrelated things, so err toward the current
  narrow, literal match rather than a fuzzier one that would produce more
  false positives.
- **Trap 3.** `link_recent_changes` runs as a cron job re-scanning
  recently-opened incidents each tick — an incident that stays open across
  many ticks (extended by new anomalies, per `worker/app/correlation/
  job.py`'s own `_extend_incident`) must not get re-linked to the same
  change record repeatedly. The composite primary key
  `(incident_id, ai_change_record_id)` on `incident_change_links` already
  makes a duplicate insert a conflict — use `ON CONFLICT DO NOTHING`
  (the same idiom `worker/app/correlation/job.py::_attach` already uses
  for `incident_anomalies`), not a pre-check-then-insert that has a race
  window.
- **Trap 4.** The new `importlinter` contract only forbids `app.memory` →
  `app.rag`. It does *not* forbid `app.rag` → `app.memory` (nothing in
  Phase 21-25 needs that direction, and adding a forbidden-both-ways pair
  preemptively for a coupling that doesn't exist yet is exactly the kind
  of speculative rule invariant 8's own "don't build a more elaborate
  rules engine than justified" reasoning warns against) — don't copy the
  existing anomaly/rag contract's *symmetric* two-contract shape here
  without checking whether this pairing actually needs both directions
  forbidden. It doesn't, yet.

---

## Phase 24 — Expose the memory to agents via MCP

### Goal

A small MCP server (Python, matching this project's own stack — see
`mcp-builder`'s guidance on the Python/FastMCP path) exposing Phase 21–23's
data as read-only tools a coding agent can call *before* making a change:
has this file caused a problem before, what's declared-coupled to it, what
was decided about a given topic and why. This is a retrieval interface over
data Culprit already owns — not a new static-analysis engine, not a code
graph, and not a write path (an agent calling these tools never creates or
edits a record; that still only happens via Phase 21's own hook and human-
facing endpoints).

### Depends on

Phase 21 (the data), Phase 23 (the links that make `culprit_file_history`
actually useful — a version of this phase built directly on Phase 21 alone,
skipping 23, would only be able to answer "what changed here," not "what
changed here and what did it cause," which is the actually differentiating
answer). Does not depend on Phase 22 directly, only through 23.

### Out of scope

- **A write-capable tool** (e.g. "record this decision" callable directly
  by an agent mid-session). Every write path stays exactly where Phases
  21/23 put it — a human-facing endpoint, or the automatic commit-time
  hook. An MCP tool that lets an agent write directly to `architecture_
  decisions` mid-conversation, before a human has actually reviewed and
  approved the decision, undermines the whole reason decisions are
  separated from AI change records in the first place.
- **Comprehensive API coverage of every Phase 21-23 endpoint as a 1:1 MCP
  tool.** The `mcp-builder` guidance's own tension between "comprehensive
  coverage" and "workflow tools" resolves toward workflow tools here,
  deliberately — the four tools below (Steps) are chosen for what a coding
  agent actually needs to ask *before* changing something, not a
  mechanical wrapper around every REST route.
- **Deploying this as a shared, multi-user network service** in
  `docker-compose.prod.yml`. `docs/SELF_HOSTED_PLAN.md` invariant "one
  Culprit install serves one team, no multi-tenancy" extends here — this
  runs locally, stdio transport, alongside a developer's own Claude Code
  session, reading whichever Postgres that install already points at
  (local dev or a real deployed instance a team runs their agents against).
  A remote, streamable-HTTP, multi-client version is a real, larger, later
  decision, not this phase's scope.
- **Any tool that calls an LLM itself.** This server does retrieval
  (embedding a query via the existing `embed_query`, then a DB read) — it
  never generates a narrative, summary, or judgment call of its own.
  Invariant 8 extends here too: an MCP tool is still part of this system,
  and "ask an LLM whether this file looks risky" inside a tool
  implementation is the same violation as inside a hook.

### Schema changes

None directly. One new DB role, in a small migration:

```sql
CREATE ROLE "mcp-reader" LOGIN PASSWORD :mcp_reader_password;
GRANT USAGE ON SCHEMA public TO "mcp-reader";
GRANT SELECT ON postmortems, architecture_decisions, ai_change_records,
  invariant_violations, incident_change_links, incident_candidates,
  anomalies, services, service_dependencies
TO "mcp-reader";
```

A new, dedicated, read-only role rather than reusing `api-reader` —
invariant 10's exception case: this genuinely is a new trust domain (a
process an agent's own tooling talks to directly, distinct from the
dashboard API's own request path), not the same conceptual writer as
`postmortem-writer`'s domain.

### API surface

Not HTTP — MCP tools, stdio transport, following the Python/FastMCP pattern
from the loaded `mcp-builder` skill (`@mcp.tool` registration, Pydantic
input models, `readOnlyHint: true` on every tool since none of them write):

```
culprit_search_memory(query: str, record_types: list[Literal["postmortem","decision","ai_change"]] = all three, top_k: int = 5)
    -> list of {type, id, title, summary/body snippet, similarity, url}
    Embeds `query` via the existing embed_query (worker/app/rag/embeddings.py)
    and calls Phase 21's retrieve_similar_records directly against the DB —
    no HTTP round-trip through api/, since this server has its own
    mcp-reader connection.

culprit_file_history(file_path: str, limit: int = 10)
    -> list of {commit_sha, summary, committed_at, violations: [...], linked_incidents: [...]}
    ai_change_records whose files_changed contains file_path, most recent
    first, each annotated with any Phase 22 violations and Phase 23
    incident links that record has.

culprit_coupled_files(file_path: str)
    -> list[str] -- the other side of any declared pairing (Phase 22's
    scripts/coupled_files.yaml) this path appears in. Empty list, not an
    error, when the path isn't declared as coupled to anything.

culprit_architecture_decisions(query: str | None = None, limit: int = 10)
    -> list of {id, title, body, created_at} -- query is optional (bare
    "list recent decisions" is a real, common call); when present, this
    is retrieve_similar_records scoped to record_types=["decision"].
```

Every tool's description states plainly, in the text an agent reads before
calling it, that results are historical/observed facts from this specific
repository, not a live static analysis — matching `mcp-builder`'s own
"actionable, accurate descriptions" guidance and pre-empting an agent
over-trusting `culprit_coupled_files`'s empty-list case as "nothing is
coupled to this file" rather than "nothing is *declared* coupled" (see
Known Trap 2).

### Files touched

| Path | Action |
| --- | --- |
| `api/migrations/versions/<rev>_mcp_reader_role.py` | NEW |
| `mcp_server/pyproject.toml`, `mcp_server/__init__.py`, `mcp_server/server.py`, `mcp_server/tools.py`, `mcp_server/config.py` | NEW — a fourth small uv project alongside `api/`, `worker/`, `demo-services/`, matching this repo's existing one-project-per-deployable-unit convention rather than folding it into `api/` or `worker/` |
| `mcp_server/Dockerfile` | NEW — not wired into `docker-compose.prod.yml` (Out of scope), but present so a team can build and run it themselves |
| `scripts/bootstrap_env.py` | EDIT — generate `MCP_READER_DB_PASSWORD` |
| `infra/.env.prod.example` | EDIT — `MCP_READER_DB_PASSWORD`, `MCP_READER_DATABASE_URL` |
| `docs/AI_NATIVE_INSTRUMENTATION.md` | NEW — the copyable guide for pointing a Claude Code (or other MCP-capable) session's own `.mcp.json`/config at a running instance of this server, mirroring `docs/INSTRUMENTATION.md`'s own role for the ingest path |

### Steps

1. Scaffold `mcp_server/` as its own uv project. Depends on `shared/
   culprit_shared` for nothing new — it talks to Postgres directly via
   its own `mcp-reader` engine, and to Voyage directly via the same
   `embed_query` logic `worker/app/rag/embeddings.py` already has (copy,
   not import — `mcp_server` and `worker` are separate deployable units
   the same way `api`/`worker`/`demo-services` already are, per this
   project's own "no shared internals across projects beyond `shared/`"
   convention; if this duplication becomes real maintenance pain later,
   promoting `embed_query` into `shared/culprit_shared/` is a small,
   independent follow-up, not something to force into this phase).
2. Implement the four tools (API surface above) against `mcp-reader`.
   Each is a straightforward SQL read plus, for the two search-flavored
   tools, one Voyage `embed_query` call — no business logic beyond what
   Phase 21/23 already computed and stored.
3. `docs/AI_NATIVE_INSTRUMENTATION.md`: how to run `mcp_server/` locally
   (`uv run python -m mcp_server`) and register it in a Claude Code
   session's own MCP config, pointed at a running Culprit's Postgres
   (local dev, or `.env.prod`'s connection details for a real install).
4. Manual verification against a real Claude Code session: register the
   server, and from a fresh session (no other context about this repo's
   history), ask it to call `culprit_file_history` on a file with a real
   AI change record and confirm the tool call surfaces the right data
   into that session's own context.

### Acceptance criteria

- `culprit_search_memory` called with a query closely matching an existing
  postmortem's content returns that postmortem in its top results, with a
  `similarity` score, and never includes the raw embedding vector.
- `culprit_file_history` called on a file with a known AI change record,
  a known Phase 22 violation, and a known Phase 23 incident link returns
  all three, correctly nested — this is the single most important
  acceptance criterion in this phase, since it's the concrete instance of
  the "closed loop" this whole plan's thesis rests on.
- `culprit_file_history` called on a file with no history returns an empty
  list, not an error.
- `culprit_coupled_files` returns the declared pair for `worker/app/db.py`
  and `api/app/db/models.py` in both directions (calling it with either
  path returns the other).
- `mcp-reader` cannot `INSERT`/`UPDATE`/`DELETE` on any table it can
  `SELECT` from — assert with a role-scoped connection, same pattern as
  every prior phase's own least-privilege test.
- A fresh Claude Code session with this server registered, given no other
  context, can correctly answer "has this file caused problems before?"
  for a file with real history, using only the tool's output — verified
  live, per the user's own instruction that MCP-adjacent work gets checked
  against a real session, not assumed from the tool's return shape alone.
- `just lint`, `just typecheck`, `just test` all pass for the new
  `mcp_server/` project; CI's build matrix gains a fourth entry.

### Tests

- `mcp_server/tests/test_tools.py` — each tool against a real (test
  container) Postgres seeded with known Phase 21/23 data — the four
  positive cases in Acceptance criteria above, plus each tool's own empty-
  result case.
- `mcp_server/tests/test_mcp_reader_role.py` — the least-privilege
  assertion above.
- No LLM-narrative-generation test needed (there is none to test — Out of
  scope explicitly forbids it), but a structural test asserting no tool
  implementation calls anything other than `embed_query` on the Voyage
  client (never a chat/completion endpoint) is cheap and worth adding,
  mirroring Phase 22/23's own structural no-LLM-import tests.

### Rollback

Purely additive — a new project, a new role, new docs. Nothing existing
changes. The migration's `downgrade()` drops the role; a team already
running the MCP server locally just loses read access on next connection
attempt, no data implication either direction.

### Known traps

- **Trap 1.** `mcp_server` importing `worker/app/rag/embeddings.py`
  directly (instead of duplicating `embed_query`) is the obvious-looking
  shortcut and the wrong one — `worker` and `mcp_server` are separate uv
  projects with no path dependency between them today, and adding one
  purely to avoid a ~15-line duplication reintroduces exactly the kind of
  cross-project coupling this repo's `shared/culprit_shared/` package
  exists specifically to avoid doing informally. Duplicate the function;
  promote it to `shared/` later if the duplication actually becomes a
  maintenance problem, not preemptively.
- **Trap 2.** `culprit_coupled_files` returning an empty list is
  ambiguous between "genuinely nothing is coupled here" and "coupling
  exists but was never declared in `scripts/coupled_files.yaml`" (Phase
  22's registry is seeded with exactly one pair — most real couplings in
  any given codebase using this system will not be declared). The tool's
  own description (API surface) must say this plainly, or an agent will
  reasonably over-trust an empty result as "safe to change freely," which
  is a worse outcome than the tool not existing at all.
- **Trap 3.** A stdio MCP server run via `uv run python -m mcp_server`
  needs `MCP_READER_DATABASE_URL` in its environment at startup the same
  way every other engine in this codebase reads its DB URL from `os.
  environ` at import/startup time — a session that registers this server
  without that env var set fails obscurely (a bare connection error deep
  in a tool call, not a clear "you forgot to set this" message at
  startup). Fail loudly and immediately on missing config, matching every
  existing `_require_env`-style pattern already used throughout `api/
  migrations/versions/` and `scripts/bootstrap_env.py`.

---

## Phase 25 — Scoped visualization

### Goal

A human-facing view over the exact same Phase 21+23 data Phase 24 exposes
to agents — task-specific views, not a whole-codebase graph. CodeSee (an
AI-powered code-visualization product, founded 2019) was acquired by
GitKraken in May 2024, and its standalone product — codebase maps, team
tours, the whole-repo-as-one-graph pitch — was discontinued as an
independent offering, folded into GitKraken's broader DevEx platform
instead of continuing to stand on its own. That's the cautionary precedent
this phase is designed against: "visualize the entire codebase as one
graph" has already been tried, by a funded, dedicated company, and didn't
hold up as a standalone bet. This phase deliberately does not repeat that
shape — every view below answers a specific question directly from Phase
21-23's existing schema, none of them require building a static+runtime
code graph to exist first.

### Depends on

Phase 21 and Phase 23 (the data and the links). Explicitly does not depend
on Phase 24 — see §2's correction. Phase 13 for routing conventions
(already merged, listed for completeness since every frontend phase in
`docs/SELF_HOSTED_PLAN.md` names it).

### Out of scope

- **A file/function/import dependency graph, rendered or not.** Not a
  smaller version of it either, as a "starter" toward the full graph —
  seeing this as the seed for that later avoids the actual point of the
  precedent above.
- **Any view requiring data this plan doesn't already produce.** If a
  view idea needs static analysis, runtime tracing, or anything beyond
  Phase 21-23's own tables, it doesn't belong in this phase — it's a
  different, larger bet than the one this document is making.
- **Editing anything from these views.** Every view here is read-only,
  same as `culprit_coupled_files` being read-only in Phase 24 — writes
  stay exactly where Phase 21/23 already put them.

### Schema changes

None. Every view is a read against tables Phase 21/23 already created.

### API surface

New `GET` endpoints in `api/app/memory/router.py` (Phase 21's package),
all on the existing `api-reader` engine, `require_auth`-gated like every
other read endpoint in this system:

```
GET /memory/files/{file_path:path}
    -> {file_path, ai_change_records: [...], violations: [...], linked_incidents: [...]}
    The same shape culprit_file_history returns, as an HTTP endpoint
    instead of an MCP tool -- one query function in api/app/memory/
    service.py, called from both Phase 24's server and this endpoint,
    not two independent implementations of the same read.

GET /memory/timeline?since=&limit=
    -> paginated feed of ai_change_records, each annotated with its own
       violations/linked_incidents, most recent first -- the data source
       for the dashboard view below.
```

`GET /architecture-decisions` (Phase 21) already exists and needs no
change for this phase's decisions list/detail view.

### Files touched

| Path | Action |
| --- | --- |
| `api/app/memory/router.py`, `service.py` | EDIT — the two endpoints above |
| `frontend/src/routes/MemoryFile.tsx` | NEW — the file-history view |
| `frontend/src/routes/MemoryTimeline.tsx` | NEW — the dashboard-style recent-activity feed |
| `frontend/src/routes/ArchitectureDecisionList.tsx`, `ArchitectureDecisionEditor.tsx` | NEW — directly mirrors `PostmortemList.tsx`/`PostmortemEditor.tsx`'s existing pattern |
| `frontend/src/hooks/useMemory.ts` | NEW |
| `frontend/src/routes/AppRoutes.tsx` | EDIT — new routes under `/memory/*` |
| `frontend/src/components/layout/Nav.tsx` | EDIT — nav links, same non-admin-gated pattern postmortems already use |

### Steps

1. `GET /memory/files/{file_path}` and `GET /memory/timeline` in `api/app/
   memory/`, sharing query logic with Phase 24's MCP tools (Files touched
   note above) rather than reimplementing the same reads a second time.
2. `MemoryFile.tsx`: given a `file_path` (route param, URL-encoded — file
   paths contain `/`, so this needs `:path*`-style matching or an encoded
   single segment; check `react-router-dom`'s current syntax for this
   rather than assuming, the same "verify, don't assume" discipline this
   whole plan was built on), render the three lists (changes, violations,
   linked incidents) in reverse-chronological order. Linked incidents
   link to the existing `/incidents/:incidentId` route (Phase 13); linked
   commits don't need to link anywhere further (there's no commit-detail
   view in this plan) but should show the commit SHA and summary plainly.
3. `MemoryTimeline.tsx`: the `/memory/timeline` feed, styled consistently
   with the existing incident `Timeline.tsx` component's own visual
   conventions (per `docs/IMPLEMENTATION_PLAN.md` §3's voice/personality
   charter, which still governs every UI surface this project adds, not
   just the original MVP's).
4. `ArchitectureDecisionList.tsx`/`Editor.tsx`: a direct copy-and-adapt of
   `PostmortemList.tsx`/`PostmortemEditor.tsx`, same skeleton-prefill
   convention, same non-admin `require_auth` gating.
5. Wire routes and nav links.

### Acceptance criteria

- `/memory/files/<path>` for a file with real Phase 21/23 history renders
  all three lists correctly, verified live in the browser against real
  data (not just the API response shape) — matching this whole
  programme's own established "verified live" bar for anything user-
  facing.
- `/memory/files/<path>` for a file with no history renders a real empty
  state (per `docs/IMPLEMENTATION_PLAN.md` §3's voice charter — dry and
  specific, not a spinner that never resolves), not a blank page or an
  error.
- `/memory/timeline` paginates correctly and reflects a newly-created
  change record (from a live commit inside a Claude Code session, per
  Phase 21's own capture mechanism) within one poll interval of it being
  created — the actual end-to-end proof that a real commit becomes real
  visible memory a human can see without querying the database directly.
- Architecture decision create/edit/delete works end-to-end through the
  UI, mirroring Phase 18's own postmortem UI verification.
- `npm run lint` (oxlint) and `tsc -b` both clean; CI green.

### Tests

- `api/tests/test_memory_api.py` — EDIT for the two new `GET` endpoints
  (empty-history case, populated case, pagination on `/memory/timeline`).
- Frontend: per `docs/SELF_HOSTED_PLAN.md` Phase 13's own precedent, this
  repo still has no frontend test runner as of Phase 20 — verify manually
  against the acceptance criteria above and note that in the PR
  description, exactly as Phase 13 did; standing up Vitest/Testing
  Library is still its own separate decision, not something to bundle
  into this phase either.

### Rollback

Pure frontend + read-only API additions. Revert the commit; no schema, no
data, no write-path implication either direction.

### Known traps

- **Trap 1.** The temptation this phase most invites is "since we're
  building a file view, why not add a small graph of related files here
  too" — resist it specifically because of the CodeSee precedent this
  phase's own Goal section is built around; a small graph today is
  exactly how a whole-codebase graph starts, one reasonable-looking
  addition at a time.
- **Trap 2.** `file_path` as a URL path parameter needs real encoding —
  a path like `demo-services/order_service/main.py` contains `/`
  characters that a naive single-segment route param will truncate at the
  first one. Verify the actual routing behavior live (load the page for a
  real nested path) rather than trusting that whatever `react-router-dom`
  syntax looks right actually handles it — this is a very easy thing to
  get subtly wrong and not notice until a real nested path is tested.
- **Trap 3.** `MemoryTimeline.tsx`'s poll interval and empty/loading
  states should follow the exact conventions `usePostmortems`/
  `useTopologySuggestions` already established (30s poll, `isPending`/
  `isError` states, mutation-driven cache invalidation for anything this
  phase's own actions touch) rather than inventing a new data-fetching
  convention for one more list view — consistency across list views in
  this codebase is itself a real quality bar this project has held to
  through every prior phase.

---

## Appendix — New environment variables introduced by this plan

| Variable | Phase | Purpose |
| --- | --- | --- |
| `AGENT_AUTOMATION_TOKEN` | 21 | Bearer credential the commit-capture hook uses to authenticate `POST /ai-change-records` without a human JWT |
| `MCP_READER_DB_PASSWORD`, `MCP_READER_DATABASE_URL` | 24 | The MCP server's own read-only Postgres role |

Both follow `scripts/bootstrap_env.py`'s existing generate-and-escape
pattern (`docs/SELF_HOSTED_PLAN.md` Phase 17) — add them to
`GENERATED_SECRETS`/`build_env`, don't hand-document a manual generation
step anywhere.
