"""create anomaly detector role

Revision ID: fef34f6aef3f
Revises: 5df76487a02f
Create Date: 2026-08-02 20:42:31.749118

A fourth least-privilege role, alongside ingestion-writer, api-reader,
and ingest-gateway: Phase 4's anomaly-scoring job needs to read
raw_events (its input) and write anomalies (its output), and nothing
else. It deliberately doesn't reuse ingestion-writer (INSERT-only on
raw_events — no SELECT) or api-reader (SELECT-only, no writes anywhere,
and scoped to the dashboard API's trust boundary, not this job's).
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fef34f6aef3f"
down_revision: str | None = "5df76487a02f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANOMALY_DETECTOR_ROLE = "anomaly-detector"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("ANOMALY_DETECTOR_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{ANOMALY_DETECTOR_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{ANOMALY_DETECTOR_ROLE}"')
    op.execute(f'GRANT SELECT ON raw_events TO "{ANOMALY_DETECTOR_ROLE}"')
    op.execute(f'GRANT INSERT ON anomalies TO "{ANOMALY_DETECTOR_ROLE}"')


def downgrade() -> None:
    op.execute(
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{ANOMALY_DETECTOR_ROLE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{ANOMALY_DETECTOR_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{ANOMALY_DETECTOR_ROLE}"')
