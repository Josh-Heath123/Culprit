"""seed products

Revision ID: 0002_seed_products
Revises: 0001_create_products

One million products in 200 categories, generated in the database itself
and identical on every run (no randomness). The size is chosen so that
reading one category by a sequential scan — the whole table, about 80 MB —
takes tens to hundreds of milliseconds, while the same read through an
index on `category` touches only that category's 5,000 rows and takes well
under a millisecond: a gap wider than any statement budget Phase 37 part 3
will declare, on a laptop or a CI runner alike.
"""

from alembic import op

revision: str = "0002_seed_products"
down_revision: str | None = "0001_create_products"

ROWS = 1_000_000
CATEGORIES = 200


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO products (id, sku, category, name, price_cents)
        SELECT n,
               'SKU-' || lpad(n::text, 7, '0'),
               'category-' || lpad((n % {CATEGORIES})::text, 3, '0'),
               'Product ' || n,
               100 + (n * 37) % 10000
        FROM generate_series(1, {ROWS}) AS n
        """
    )
    # Fresh statistics, so the planner sees the table as it is.
    op.execute("ANALYZE products")


def downgrade() -> None:
    op.execute("DELETE FROM products")
