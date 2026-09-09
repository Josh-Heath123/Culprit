---
paths:
  - "api/migrations/**"
  - "api/app/db/**"
  - "worker/app/db.py"
  - "api/app/*/config.py"
---

# Database rules

## Least privilege

One Postgres role per job. Ten exist: `ingestion-writer`, `api-reader`,
`ingest-gateway`, `anomaly-detector`, `correlation-engine`, `root-cause-writer`,
`registry-admin`, `auth-service`, `postmortem-writer`, `mcp-reader`.

**If a component needs a write the current roles cannot do, add a role. Do not
widen an existing one.** A role is reused only when the new surface is genuinely
the same trust domain (`postmortem-writer` covering engineering memory is the one
sanctioned example, and it is documented as such).

Column-level grants are used where they express the real need — `ingest-gateway`
has `UPDATE (last_used_at)` on `api_keys` and nothing else on that table. Prefer
that over a table grant when only one column is written.

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
