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
   own Alembic migrations, which create and seed `products` and (0003)
   index it. To head, or to INVENTORY_MIGRATION_TARGET when it is set: the
   tests that need the database as an earlier revision left it (Phase 37
   part 3's missing index is the database at 0002).

Idempotent: a second run changes nothing. The role's password is set on
every run to the one INVENTORY_DATABASE_URL carries, which the quickstart
generates (infra/.env.prod): a Postgres volume from before the password
was generated still works. Culprit's own database is never touched — a
separate database, with its own role.

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
    if role != "inventory" or database != "inventory":
        # This job sets the role's password on every run, so it is held to
        # the demo's own role: pointed at one of Culprit's, it would reset it.
        raise SystemExit(
            f"inventory-db-setup sets up the role and database `inventory` only, not {role!r}"
        )
    if not password:
        # The compose file passes an empty password when infra/.env.prod
        # predates INVENTORY_DB_PASSWORD; `just quickstart` adds one.
        raise SystemExit(
            "INVENTORY_DATABASE_URL carries no password: infra/.env.prod has no "
            "INVENTORY_DB_PASSWORD. Run `just quickstart`, which generates one."
        )

    with _connect_as_admin() as connection:
        exists = (
            connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            is not None
        )
        connection.execute(
            sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                sql.SQL("ALTER" if exists else "CREATE"),
                sql.Identifier(role),
                sql.Literal(password),
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

    target = os.environ.get("INVENTORY_MIGRATION_TARGET", "") or "head"
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    command.upgrade(config, target)
    print(f"inventory-service's database {database} is at {target}, owned by {role}")


if __name__ == "__main__":
    main()
