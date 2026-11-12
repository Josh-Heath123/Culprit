"""create items

Revision ID: 0001_create_items
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_items"
down_revision: str | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
    )
    op.create_index("ix_items_sku", "items", ["sku"])


def downgrade() -> None:
    op.drop_index("ix_items_sku", table_name="items")
    op.drop_table("items")
