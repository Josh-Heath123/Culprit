"""add invoices.reference

Revision ID: 0002
Revises: 0001

Note what is *not* here: `total_cents`, which models.py declares. That
omission is the fault this component exists to demonstrate.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"


def upgrade() -> None:
    op.add_column("invoices", sa.Column("reference", sa.String(length=64), nullable=False))


def downgrade() -> None:
    op.drop_column("invoices", "reference")
