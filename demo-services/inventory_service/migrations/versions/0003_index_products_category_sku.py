"""index products by category, then sku

Revision ID: 0003_products_category_sku
Revises: 0002_seed_products

GET /products reads the first 50 of one category's products in sku order.
Without an index led by `category`, Postgres walks `ix_products_sku` for
the order and filters `category` row by row, across a million rows. This
index serves both the filter and the order, so the read stops after 50
entries (Phase 37 part 2 measured it within the 20 ms statement budget,
where an index on `category` alone is not).

The fault library's database fault is this revision missing: the tree
holds 0001-0002 and the database is at 0002. Its known fix is the commit
that adds this file, with the database upgraded to it.
"""

from alembic import op

revision: str = "0003_products_category_sku"
down_revision: str | None = "0002_seed_products"


def upgrade() -> None:
    op.create_index("ix_products_category_sku", "products", ["category", "sku"])


def downgrade() -> None:
    op.drop_index("ix_products_category_sku", table_name="products")
