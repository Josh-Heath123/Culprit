"""create correlation engine role

Revision ID: a0cac3233f8d
Revises: 15cd15847626
Create Date: 2026-08-02 21:45:58.110231

A fifth least-privilege role, alongside ingestion-writer, api-reader,
ingest-gateway, and anomaly-detector: Phase 5's correlation job reads
anomalies (its input) and reads/writes incident_candidates +
incident_anomalies (its output and its own bookkeeping of what's already
correlated). It doesn't reuse anomaly-detector (INSERT-only on
anomalies, no incident tables at all) or api-reader (read-only, no
writes anywhere, and scoped to the dashboard API's boundary, not this
job's).
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a0cac3233f8d"
down_revision: str | None = "15cd15847626"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORRELATION_ENGINE_ROLE = "correlation-engine"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("CORRELATION_ENGINE_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{CORRELATION_ENGINE_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{CORRELATION_ENGINE_ROLE}"')
    op.execute(f'GRANT SELECT ON anomalies TO "{CORRELATION_ENGINE_ROLE}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE ON incident_candidates TO "{CORRELATION_ENGINE_ROLE}"'
    )
    op.execute(f'GRANT SELECT, INSERT ON incident_anomalies TO "{CORRELATION_ENGINE_ROLE}"')


def downgrade() -> None:
    op.execute(
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{CORRELATION_ENGINE_ROLE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{CORRELATION_ENGINE_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{CORRELATION_ENGINE_ROLE}"')
