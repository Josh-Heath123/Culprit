-- The same schema one revision earlier: 0003_add_order_lines has not
-- been applied, so there is no order_lines table and alembic_version
-- still says 0002_add_status. The deploy shipped the code; nobody ran
-- the migration.
CREATE TABLE orders (
    id             SERIAL PRIMARY KEY,
    customer_email VARCHAR(320) NOT NULL,
    total_cents    INTEGER NOT NULL,
    status         VARCHAR(32) NOT NULL,
    placed_at      TIMESTAMPTZ NOT NULL,
    cancelled_at   TIMESTAMPTZ
);

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('0002_add_status');
