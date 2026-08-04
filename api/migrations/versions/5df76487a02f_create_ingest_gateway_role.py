"""create ingest gateway role

Revision ID: 5df76487a02f
Revises: 48c0b29fa215
Create Date: 2026-08-02 19:58:17.832138

A third least-privilege role, alongside ingestion-writer and api-reader
from Phase 1: ingest-gateway only needs to read api_keys to authenticate
incoming requests. It deliberately does NOT reuse api-reader — that role
is scoped to the dashboard/incident API (Phase 7), a different trust
boundary, and a compromised ingest-gateway shouldn't be able to read
incidents/postmortems it has no reason to see.
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5df76487a02f"
down_revision: str | None = "48c0b29fa215"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INGEST_GATEWAY_ROLE = "ingest-gateway"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("INGEST_GATEWAY_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{INGEST_GATEWAY_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{INGEST_GATEWAY_ROLE}"')
    op.execute(f'GRANT SELECT ON api_keys TO "{INGEST_GATEWAY_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{INGEST_GATEWAY_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{INGEST_GATEWAY_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{INGEST_GATEWAY_ROLE}"')
