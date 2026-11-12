"""inventory-service's own database (Phase 37 part 1, P8).

Optional: with INVENTORY_DATABASE_URL unset — the fault library's stack —
the list route answers 503 and every other route is unchanged.
"""

import os
from functools import cache

from sqlalchemy import Engine, create_engine


def sqlalchemy_url(url: str) -> str:
    """The URL with psycopg (3) as SQLAlchemy's driver, which this project
    depends on; a plain `postgresql://` would ask for psycopg2."""
    scheme, separator, rest = url.partition("://")
    if separator and scheme in ("postgresql", "postgres"):
        return f"postgresql+psycopg://{rest}"
    return url


@cache
def engine() -> Engine | None:
    url = os.environ.get("INVENTORY_DATABASE_URL", "")
    if not url:
        return None
    return create_engine(sqlalchemy_url(url), pool_size=5, pool_pre_ping=True)
