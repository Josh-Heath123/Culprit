"""create db roles

Revision ID: cc323b6c7779
Revises: e2cab79bcc93
Create Date: 2026-08-02 19:09:01.287606

Two least-privilege roles, versioned here rather than a hand-run init
script, per CLAUDE.md's rule to design against role boundaries from the
first query instead of retrofitting them later:

- ingestion-writer: INSERT-only on raw_events. Nothing else — a compromised
  ingestion endpoint should not be able to read or alter anything it
  doesn't need to touch.
- api-reader: SELECT-only, on raw_events/anomalies/incident_candidates/
  postmortems *and* the incident_anomalies join table. The join table
  wasn't named explicitly in the four-table list, but without SELECT on it
  the API can't answer "which anomalies belong to this incident" — the
  entire reason the table exists — so it's included as read-only alongside
  the rest.

Both passwords come from the environment (INGESTION_WRITER_PASSWORD /
API_READER_PASSWORD — see api/.env.example) rather than being hardcoded
here, per the security checklist in docs/IMPLEMENTATION_PLAN.md.
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc323b6c7779"
down_revision: str | None = "e2cab79bcc93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INGESTION_WRITER = "ingestion-writer"
API_READER = "api-reader"
READABLE_TABLES = (
    "raw_events",
    "anomalies",
    "incident_candidates",
    "incident_anomalies",
    "postmortems",
)


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    ingestion_writer_password = _require_env("INGESTION_WRITER_PASSWORD")
    api_reader_password = _require_env("API_READER_PASSWORD")

    op.execute(
        f'CREATE ROLE "{INGESTION_WRITER}" LOGIN '
        f"PASSWORD {_pg_string_literal(ingestion_writer_password)}"
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{INGESTION_WRITER}"')
    op.execute(f'GRANT INSERT ON raw_events TO "{INGESTION_WRITER}"')

    op.execute(
        f'CREATE ROLE "{API_READER}" LOGIN '
        f"PASSWORD {_pg_string_literal(api_reader_password)}"
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{API_READER}"')
    op.execute(f'GRANT SELECT ON {", ".join(READABLE_TABLES)} TO "{API_READER}"')


def downgrade() -> None:
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{API_READER}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{API_READER}"')
    op.execute(f'DROP ROLE IF EXISTS "{API_READER}"')

    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{INGESTION_WRITER}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{INGESTION_WRITER}"')
    op.execute(f'DROP ROLE IF EXISTS "{INGESTION_WRITER}"')
