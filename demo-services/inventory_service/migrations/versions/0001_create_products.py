"""create products

Revision ID: 0001_create_products
Revises:

inventory-service's own table (Phase 37 part 1, PERFORMANCE_PLAN.md P8):
the catalogue the list route reads. `sku` is indexed; `category`, which the
list route filters on, deliberately is not — Phase 37 part 3 plants its
missing-index fault on exactly that, and the known fix is a migration that
adds it.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_products"
down_revision: str | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_table("products")
