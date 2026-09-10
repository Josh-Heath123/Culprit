-- The schema cli/testdata/fixtures/fastapi-orders's three migrations
-- leave behind, at the head revision. Matches orders_api/models.py
-- column for column, nullability included — this is the environment
-- that is right.
CREATE TABLE orders (
    id             SERIAL PRIMARY KEY,
    customer_email VARCHAR(320) NOT NULL,
    total_cents    INTEGER NOT NULL,
    status         VARCHAR(32) NOT NULL,
    placed_at      TIMESTAMPTZ NOT NULL,
    cancelled_at   TIMESTAMPTZ
);

CREATE TABLE order_lines (
    id       SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (id),
    sku      VARCHAR(64) NOT NULL,
    quantity INTEGER NOT NULL
);

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('0003_add_order_lines');
