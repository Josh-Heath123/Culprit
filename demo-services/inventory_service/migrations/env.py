"""Alembic's environment for inventory-service's own database.

The connection string comes from INVENTORY_DATABASE_URL, in the
environment, never from a file: the same variable the service reads.
"""

import os

from alembic import context
from inventory_service.db import sqlalchemy_url
from sqlalchemy import create_engine

url = sqlalchemy_url(os.environ["INVENTORY_DATABASE_URL"])


def run() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run()
