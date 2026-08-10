"""wire the flywheel

Revision ID: 8387f175770d
Revises: f8eb1412d86f
Create Date: 2026-08-10 20:37:43.360553

Phase 23 (docs/AI_NATIVE_PLAN.md): connects Phase 21 (engineering memory)
and Phase 22 (deterministic verification) to each other and to the
existing incident-correlation pipeline, automatically:

- `invariant_violations`: one row per Phase 22 hook-time violation
  (docs/AI_NATIVE_PLAN.md Phase 23 Step 2). `ai_change_record_id` is
  nullable and stays NULL from that write path -- no commit exists yet
  at hook-fire time (Known Trap 1) -- unlike a hypothetical CI-time
  write path that could resolve one after the fact (not built in this
  phase; see PR description).
- `incident_change_links`: one row per (incident, AI change record) the
  worker's new `link_recent_changes` cron job (worker/app/memory/
  link_job.py) proposes via a fixed 30-minute lookback + service/file
  substring heuristic (Known Trap 2 -- deliberately crude, never
  fuzzy). The composite PK doubles as the idempotency guard the job's
  own `ON CONFLICT DO NOTHING` relies on (Known Trap 3).

No new DB role (AI_NATIVE_PLAN.md invariant 10): `invariant_violations`
extends `postmortem-writer`'s existing grants (same trust domain as the
other engineering-memory tables it already owns), and
`incident_change_links` extends `correlation-engine`'s (the linking job
runs as part of worker's existing correlation-adjacent cron
infrastructure, not a new engine). `correlation-engine` also gains
SELECT on `ai_change_records` here -- not shown in the plan's own
illustrative grants block, but a strict necessity: `link_recent_changes`
reads `ai_change_records.committed_at`/`files_changed` under this exact
role, and had no prior access to that table at all (Phase 21 only
granted it to `postmortem-writer`/`api-reader`).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8387f175770d"
down_revision: str | None = "f8eb1412d86f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSTMORTEM_WRITER = "postmortem-writer"
CORRELATION_ENGINE = "correlation-engine"
API_READER = "api-reader"


def upgrade() -> None:
    op.create_table(
        "invariant_violations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("invariant_name", sa.String(), nullable=False),
        sa.Column(
            "file_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column(
            "ai_change_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_change_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "invariant_name IN ('migration_symmetry', 'coupled_files')",
            name="ck_invariant_violations_invariant_name",
        ),
    )

    op.create_table(
        "incident_change_links",
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ai_change_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_change_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("link_reason", sa.String(), nullable=False),
    )

    op.execute(f'GRANT SELECT, INSERT ON invariant_violations TO "{POSTMORTEM_WRITER}"')
    op.execute(f'GRANT SELECT, INSERT ON incident_change_links TO "{CORRELATION_ENGINE}"')
    op.execute(f'GRANT SELECT ON ai_change_records TO "{CORRELATION_ENGINE}"')
    op.execute(
        f'GRANT SELECT ON invariant_violations, incident_change_links TO "{API_READER}"'
    )


def downgrade() -> None:
    op.execute(
        f'REVOKE SELECT ON invariant_violations, incident_change_links FROM "{API_READER}"'
    )
    op.execute(f'REVOKE SELECT ON ai_change_records FROM "{CORRELATION_ENGINE}"')
    op.execute(f'REVOKE SELECT, INSERT ON incident_change_links FROM "{CORRELATION_ENGINE}"')
    op.execute(f'REVOKE SELECT, INSERT ON invariant_violations FROM "{POSTMORTEM_WRITER}"')

    op.drop_table("incident_change_links")
    op.drop_table("invariant_violations")
