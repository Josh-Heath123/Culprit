"""postmortem write path

Revision ID: 35b434e21f5c
Revises: fbf4cb16570a
Create Date: 2026-08-06 09:00:00.000000

Phase 18: a team can finally write its own postmortems instead of only
ever seeing the eight fixture ones `seed_postmortems.py` loads once.
Four new nullable columns on `postmortems`:

- `author_user_id` -- who wrote it (Phase 16 gives us a real `users`
  table to point at now); ON DELETE SET NULL, not CASCADE, so deleting a
  user's account never deletes the postmortems they wrote.
- `updated_at` -- set by the API on every PATCH; NULL until first edited.
- `embedded_at` / `embedding_error` -- together let the UI distinguish
  "queued" (both NULL), "embedded" (embedded_at set), and "failed with
  this reason" (embedding_error set) — `embedding IS NULL` alone can't
  tell "never tried" from "tried and failed," and a postmortem that
  silently never became retrievable is the worst failure mode here
  because it looks like it worked.

New role `postmortem-writer`, used by api/app/postmortems/ for every
write (GET stays on the existing api-reader role, which already has
SELECT on postmortems -- see cc323b6c7779_create_db_roles.py). Also
granted SELECT on incident_candidates: creating a postmortem attached to
an incident (POST /postmortems's optional incident_id) validates that
incident exists before insert, for a clean 400 instead of a raw FK
violation.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "35b434e21f5c"
down_revision: str | None = "fbf4cb16570a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTMORTEM_WRITER_ROLE = "postmortem-writer"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    op.add_column(
        "postmortems",
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "postmortems", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "postmortems", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("postmortems", sa.Column("embedding_error", sa.String(), nullable=True))

    password = _require_env("POSTMORTEM_WRITER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{POSTMORTEM_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{POSTMORTEM_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON postmortems TO "{POSTMORTEM_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT ON incident_candidates TO "{POSTMORTEM_WRITER_ROLE}"')


def downgrade() -> None:
    op.execute(
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{POSTMORTEM_WRITER_ROLE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{POSTMORTEM_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{POSTMORTEM_WRITER_ROLE}"')

    op.drop_column("postmortems", "embedding_error")
    op.drop_column("postmortems", "embedded_at")
    op.drop_column("postmortems", "updated_at")
    op.drop_column("postmortems", "author_user_id")
