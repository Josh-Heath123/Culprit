# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""seed products

Revision ID: 0002_seed_products
Revises: 0001_create_products

One million products in 200 categories (category-000 to category-199),
generated in the database itself and identical on every run (no
randomness). Categories are interleaved: product n is in category n % 200,
so every category has a product every 200 skus.

That interleaving decides what a missing index costs (Q35, measured on
PostgreSQL 16). GET /products reads the first 50 of one category in sku
order. With no index led by `category`, Postgres walks `ix_products_sku`
for the order and filters `category` row by row: for a seeded category it
finds 50 matches within ~10,000 entries and stops (under a millisecond);
for a category with no products it walks the whole index (about 75 ms).
An index on `category` alone goes unused for that read, because the
planner estimates 5,000 rows for any category. Not a sequential scan.
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
