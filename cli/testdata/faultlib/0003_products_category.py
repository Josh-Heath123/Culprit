"""index products by category alone

Revision ID: 0003_products_category
Revises: 0002_seed_products

The fault library's wrong fix for its database fault (Phase 37 part 3,
cli/cmd/culprit/faultlib_test.go): an index on `category` alone, the
obvious fix and not the right one. For a category with no products the
planner estimates 5,000 rows, as for any category, and keeps walking
`ix_products_sku` for the order, so this index goes unused and the read
still walks the whole sku index (Q35). Verification must say
not_resolved.

Test data, never part of the demo: the harness copies it into
inventory-service's migrations, and into the tree the walk reads, only
for that scenario.
"""

from alembic import op

revision: str = "0003_products_category"
down_revision: str | None = "0002_seed_products"


def upgrade() -> None:
    op.create_index("ix_products_category", "products", ["category"])


def downgrade() -> None:
    op.drop_index("ix_products_category", table_name="products")
