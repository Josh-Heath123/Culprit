"""Set up inventory-service's own database (Phase 37 part 1, P8).

The demo's setup, run once by `just quickstart` (and by the Docker tests),
never by Culprit:

1. As the server's superuser (INVENTORY_ADMIN_HOST, _PORT, _USER,
   _PASSWORD and _DB, separately: a generated password may hold characters
   a URL would need escaped): create the `inventory`
   role and the `inventory` database it owns, if they do not exist, and
   create the `pg_stat_statements` extension in that database — an
   extension that is not trusted, so only a superuser may create it.
2. As the database's owner (INVENTORY_DATABASE_URL): apply the service's
   own Alembic migrations, which create and seed `products`.

Idempotent: a second run changes nothing. Culprit's own database is never
touched — a separate database, with its own role.

    python -m inventory_service.setup_db
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql


def _connect_as_admin(dbname: str | None = None) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["INVENTORY_ADMIN_HOST"],
        port=int(os.environ.get("INVENTORY_ADMIN_PORT", "5432")),
        user=os.environ["INVENTORY_ADMIN_USER"],
        password=os.environ["INVENTORY_ADMIN_PASSWORD"],
        dbname=dbname or os.environ["INVENTORY_ADMIN_DB"],
        autocommit=True,
    )


def main() -> None:
    owner = urlsplit(os.environ["INVENTORY_DATABASE_URL"])
    role, password = owner.username or "inventory", owner.password or ""
    database = owner.path.lstrip("/") or "inventory"

    with _connect_as_admin() as connection:
        if (
            connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            is None
        ):
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        if (
            connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
            ).fetchone()
            is None
        ):
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
    with _connect_as_admin(dbname=database) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

    config = Config(str(Path(__file__).with_name("alembic.ini")))
    command.upgrade(config, "head")
    print(f"inventory-service's database {database} is at head, owned by {role}")


if __name__ == "__main__":
    main()
