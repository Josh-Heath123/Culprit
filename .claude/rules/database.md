---
paths:
  - "api/migrations/**"
  - "api/app/db/**"
  - "worker/app/db.py"
  - "api/app/*/config.py"
---

# Database rules

## Least privilege

One Postgres role per job. Seventeen exist: `ingestion-writer`, `api-reader`,
`ingest-gateway`, `anomaly-detector`, `correlation-engine`, `root-cause-writer`,
`registry-admin`, `auth-service`, `postmortem-writer`, `mcp-reader`,
`fact-writer`, `capture-writer` (Phase 30 — INSERT on `captures` and
`configured_facts`, SELECT on `captures`, nothing else; a new role rather than
the third reuse of `fact-writer` this file warns about, because what a running
environment is configured to do is a different trust domain from what a
repository says about itself), `probe-writer` (Phase 31 — INSERT on `readings`
and nothing else, not even SELECT on it; a new role again, because a credential
that can post readings is one that already had reach into a running environment,
which is a wider starting position than either of the two above),
`investigation-writer` (Phase 32 — INSERT on the five investigation tables and
nothing else; field 7's rule, that every fault edge cites a reading of its own
investigation, is held by the database itself, with a composite foreign key and
a deferred constraint trigger, so a writer that skips the model still cannot
store an uncited edge), and Phase 33's three agent roles, one per write
surface — `agent-admin` (pairing codes, allowances, revocation, tasks),
`agent-registrar` (spend a pairing code, insert the agent) and
`agent-gateway` (an agent's own signed requests: nonces, claims, results,
audit entries). No role holds UPDATE or DELETE on `agent_audit_log`, and
triggers refuse both, and TRUNCATE, to the owner as well. The Phase 32
migration *narrowed* two roles:
`correlation-engine` and `root-cause-writer` lost every write on the incident
tables, which are history now.

**If a component needs a write the current roles cannot do, add a role. Do not
widen an existing one.** This is standing invariant 3 (`docs/DIAGNOSTIC_PLAN.md`
§3), whose wording is the rule of record:

> A new job, a new trust domain or a new write surface gets a new role, and a
> role's write grants are never widened. A read grant may be added to an
> existing role only for a table its *same* job needs beside one it already
> reads, with the justification written in the migration and the downgrade
> revoking it.

So **write grants are never widened**, without exception. A **read** grant may
be added, under all three conditions: same job, a table beside one the role
already reads, argued in the migration with the downgrade revoking it. The one
instance is Phase 31's `anomaly-detector` SELECT on `connections`, beside the
`components` it already read (Phase 27's rename carried its `services` grant
there), to resolve which edge a metric belongs to — `a9d2c40f7e18`. A read grant
that fails any of the three is a new role, the same as a write.

A role is reused only when the new surface is genuinely the same trust domain.
**Two** such exceptions exist, and both are documented where the reuse happens:

1. `postmortem-writer` covering engineering memory (Phase 21).
2. `fact-writer` covering `divergences` (Phase 29) — divergences are produced by
   the same CI run, from the same repository, under the same project token, as
   the facts they were derived from. Reasoned in `api/app/divergences/config.py`
   and in `api/migrations/versions/b8e0c3d5f214_*.py`.

If you are about to add a third, that is the signal this rule has stopped
working, not that the third one is fine. Each exception must be argued in the
migration and in the module, and the test that asserts the old boundary must be
rewritten *stronger* rather than deleted — `api/tests/test_facts_api.py`'s
`test_fact_writer_cannot_touch_the_other_planes_tables` is the worked example.

Column-level grants are used where they express the real need — `ingest-gateway`
has `UPDATE (last_used_at)` on `api_keys`, and `fact-writer` has UPDATE on nine
named columns of `divergences` and nothing else on that table. Prefer that over a
table grant whenever the writer touches a knowable subset.

This is not tidiness. `divergences.first_seen_at` answers "how long has this been
broken", and a bare table grant would have made "a repeat sighting cannot move
it" an application convention rather than something the database enforces — so a
leaked CI token could have made every open finding look new. The column list is
what turns a docstring's promise into a guarantee.

## Schema parity

`worker/app/db.py` (Core tables) and `api/app/db/models.py` (ORM) are hand-mirrored
across two separate uv projects. `scripts/check_schema_drift.py` diffs them and
fails CI on divergence.

**Nullability is part of the schema.** A column declared with only a
`server_default` and no explicit `NOT NULL` is nullable. This exact mistake has
been made four times in this repo.

## Migrations

- Historical snapshots. They do not import mutable application code.
- Every `create_table` needs a matching `drop_table`; every `add_column` a
  `drop_column`; every `GRANT ... TO "role"` a `REVOKE`/`DROP ROLE`.
  `scripts/check_migration_symmetry.py` checks this structurally on save.
- Required env vars use the `_require_env` pattern and fail loudly. Application
  config must do the same — the fail-open dev-password fallbacks in
  `api/app/*/config.py` are a known defect being removed in Phase 26, not a
  pattern to copy.

## New tables from the diagnostic plan

`readings` is a TimescaleDB hypertable (evidence, 90-day retention).
`intent_facts` and `configured_facts` are snapshot tables versioned by
`capture_id`. Every vector column gets an HNSW index in the same migration that
creates it — two existing ones were missed and sequentially scan.
