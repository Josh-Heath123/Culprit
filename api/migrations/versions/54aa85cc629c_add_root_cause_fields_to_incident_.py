"""add root cause fields to incident candidates

Revision ID: 54aa85cc629c
Revises: a0cac3233f8d
Create Date: 2026-08-03 08:42:43.273534

Phase 6 (RAG + root-cause narrative). Nullable throughout, and a 1:1
addition to incident_candidates rather than a separate table — every
incident_candidate row already exists before this phase runs (Phase 5
created it), and there is exactly one root-cause narrative per incident,
generated once, asynchronously, some time after the row itself is
created.

root_cause_evidence is JSONB, not a plain string: it holds the cited
postmortem passage(s) as structured citations (postmortem id/title plus
the quoted passage), which is what makes the narrative auditable per the
Section 3 voice charter rather than a "trust me" free-text blob.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "54aa85cc629c"
down_revision: str | None = "a0cac3233f8d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incident_candidates", sa.Column("root_cause_hypothesis", sa.String(), nullable=True)
    )
    op.add_column(
        "incident_candidates", sa.Column("root_cause_confidence", sa.String(), nullable=True)
    )
    op.add_column(
        "incident_candidates",
        sa.Column("root_cause_confidence_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "incident_candidates",
        sa.Column(
            "root_cause_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "incident_candidates",
        sa.Column("root_cause_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_incident_candidates_root_cause_confidence",
        "incident_candidates",
        "root_cause_confidence IS NULL OR root_cause_confidence IN ('High', 'Medium', 'Low')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_incident_candidates_root_cause_confidence", "incident_candidates", type_="check"
    )
    op.drop_column("incident_candidates", "root_cause_generated_at")
    op.drop_column("incident_candidates", "root_cause_evidence")
    op.drop_column("incident_candidates", "root_cause_confidence_reason")
    op.drop_column("incident_candidates", "root_cause_confidence")
    op.drop_column("incident_candidates", "root_cause_hypothesis")
