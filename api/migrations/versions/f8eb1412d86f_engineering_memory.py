"""engineering memory

Revision ID: f8eb1412d86f
Revises: e6b6bd0e99df
Create Date: 2026-08-09 13:56:32.018123

Phase 21 (docs/AI_NATIVE_PLAN.md): generalizes the postmortem write path
(Phase 18) into a small family of engineering records. `postmortems`
itself is untouched — see AI_NATIVE_PLAN.md Phase 21 Known Trap 1 for why
restructuring it into a unified table was explicitly ruled out. Two new
sibling tables instead:

- `architecture_decisions`: same shape as `postmortems` (title, body,
  embedding, author, timestamps) minus the incident linkage postmortems
  has, since a decision isn't tied to an incident.
- `ai_change_records`: one row per commit made inside a Claude Code
  session (written automatically by `.claude/hooks/capture_ai_change.sh`,
  never by hand) — `commit_sha` is UNIQUE so a hook re-fire or retry is a
  safe no-op, not a duplicate. `author_user_id` is nullable and stays NULL
  for hook-created rows; `git_author` is the raw git identity, always
  present since every commit has one.

No new DB role (AI_NATIVE_PLAN.md invariant 10): both tables extend
`postmortem-writer`'s existing grants rather than minting a new role,
since they're the same trust domain as `postmortems`. `ai_change_records`
gets no DELETE grant — a change record describes what actually happened;
it isn't user-editable content the way a postmortem or decision is.
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f8eb1412d86f"
down_revision: str | None = "e6b6bd0e99df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTMORTEM_WRITER = "postmortem-writer"
API_READER = "api-reader"


def upgrade() -> None:
    op.create_table(
        "architecture_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_error", sa.String(), nullable=True),
    )

    op.create_table(
        "ai_change_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("commit_sha", sa.String(), nullable=False, unique=True),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column(
            "files_changed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("git_author", sa.String(), nullable=True),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_error", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_ai_change_records_committed_at", "ai_change_records", ["committed_at"]
    )

    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON architecture_decisions TO "{POSTMORTEM_WRITER}"'
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON ai_change_records TO "{POSTMORTEM_WRITER}"')
    op.execute(
        f'GRANT SELECT ON architecture_decisions, ai_change_records TO "{API_READER}"'
    )


def downgrade() -> None:
    op.execute(
        f'REVOKE SELECT ON architecture_decisions, ai_change_records FROM "{API_READER}"'
    )
    op.execute(f'REVOKE SELECT, INSERT, UPDATE ON ai_change_records FROM "{POSTMORTEM_WRITER}"')
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON architecture_decisions '
        f'FROM "{POSTMORTEM_WRITER}"'
    )

    op.drop_index("ix_ai_change_records_committed_at", table_name="ai_change_records")
    op.drop_table("ai_change_records")
    op.drop_table("architecture_decisions")
