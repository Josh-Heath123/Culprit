"""create product details

Revision ID: 0004_product_details
Revises: 0003_products_category_sku

A relation the list route GET /products/details loads for each product
(Phase 39 part 2): one row per product, keyed by the product's id, so the
relation is distinct per item. A row shared by several products would be
loaded once by an ORM's identity map, its calls would fall below the item
count, and no statement would be named.

Additive: it rewrites no landed migration (Q35 (b)), and the products
table, its indexes and the missing-index fault on them are unchanged. The
missing-index fault puts the database at 0002, where this table does not
exist; nothing on that fault's walk reads it.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_product_details"
down_revision: str | None = "0003_products_category_sku"


def upgrade() -> None:
    op.create_table(
        "product_details",
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("description", sa.String(128), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=False),
    )
    # One row per seeded product, generated in the database and identical
    # on every run, as 0002 seeds products.
    op.execute(
        """
        INSERT INTO product_details (product_id, description, weight_grams)
        SELECT id, 'Details of ' || name, 50 + (id * 13) % 5000
        FROM products
        """
    )
    op.execute("ANALYZE product_details")


def downgrade() -> None:
    op.drop_table("product_details")
