"""grant ingest-gateway column-level update on api_keys.last_used_at

Revision ID: 162c7130818c
Revises: 635870479f4e
Create Date: 2026-08-05 00:00:00.000000

635870479f4e granted `ingest-gateway` SELECT on `services` but never
touched its `api_keys` grants (still just the SELECT from 5df76487a02f).
`ApiKeyStore._schedule_last_used_update()` (api/app/ingest_gateway/auth.py)
has been firing `UPDATE api_keys SET last_used_at = ...` as a
fire-and-forget background task since Phase 14 shipped, and it has been
failing on every single call with a Postgres permission error the whole
time -- caught and logged as `last_used_at_update_failed`, so silently,
in production too. Confirmed live via `psql -c "\\dp api_keys"`:
`ingest-gateway` had only `r` (SELECT).

Column-level GRANT, not a table-level one -- `ingest-gateway` should be
able to update `last_used_at` and nothing else on this table (it must
never be able to touch `key_hash`, `revoked_at`, `service_id`, etc.).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "162c7130818c"
down_revision: str | None = "635870479f4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('GRANT UPDATE (last_used_at) ON api_keys TO "ingest-gateway"')


def downgrade() -> None:
    op.execute('REVOKE UPDATE (last_used_at) ON api_keys FROM "ingest-gateway"')
