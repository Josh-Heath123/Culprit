"""add last anomaly at to incident candidates

Revision ID: 15cd15847626
Revises: fef34f6aef3f
Create Date: 2026-08-02 21:45:57.212979

incident_candidates has never been written to before Phase 5 (Phase 1
only created the empty table), so this is safe as NOT NULL with no
default — every insert path Phase 5 writes supplies it explicitly.

Note: the incident_anomalies junction table itself already exists from
Phase 1's core-schema migration (e3f8d40026c9) with the right shape
(incident_id, anomaly_id, composite PK, CASCADE FKs) — nothing to add
there.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15cd15847626"
down_revision: str | None = "fef34f6aef3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incident_candidates",
        sa.Column("last_anomaly_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("incident_candidates", "last_anomaly_at")
