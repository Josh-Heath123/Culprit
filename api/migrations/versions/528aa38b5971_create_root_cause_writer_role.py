"""create root cause writer role

Revision ID: 528aa38b5971
Revises: 54aa85cc629c
Create Date: 2026-08-03 08:44:11.902481

A sixth least-privilege role, alongside ingestion-writer, api-reader,
ingest-gateway, anomaly-detector, and correlation-engine: Phase 6's
RAG/root-cause job reads anomalies, incident_anomalies and raw_events
(to build the incident summary it embeds and retrieves against), reads
and writes postmortems (seeding + backfilling embeddings — the seed
script reuses this same role rather than adding a seventh role for one
script), and reads/writes the root_cause_* columns on the
incident_candidates it explains. It deliberately doesn't reuse
correlation-engine (no SELECT on raw_events, no access to postmortems at
all) or api-reader (read-only, a different trust boundary — Phase 7's,
not this job's).
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "528aa38b5971"
down_revision: str | None = "54aa85cc629c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROOT_CAUSE_WRITER_ROLE = "root-cause-writer"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("ROOT_CAUSE_WRITER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{ROOT_CAUSE_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT ON raw_events TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT ON anomalies TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT ON incident_anomalies TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT, UPDATE ON incident_candidates TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON postmortems TO "{ROOT_CAUSE_WRITER_ROLE}"')


def downgrade() -> None:
    op.execute(
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{ROOT_CAUSE_WRITER_ROLE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{ROOT_CAUSE_WRITER_ROLE}"')
