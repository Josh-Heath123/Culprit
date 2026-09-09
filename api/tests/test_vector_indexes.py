"""Phase 26 regression test: every embedding column has an HNSW index.

The defect: `postmortems.embedding` has had one since the first
migration, but Phase 21 added `architecture_decisions.embedding` and
`ai_change_records.embedding` with the same 1024-dimension shape and the
same cosine-similarity query pattern, and indexed neither. Both were
sequentially scanned by `worker/app/rag/retrieval.py`'s UNION ALL and
`mcp_server/tools.py`'s `search_memory` — invisible at eight fixture
rows, not invisible at eight thousand.

Written as "every vector column", not "these two columns", deliberately.
The failure mode is a *new* embedding column being added without an
index, so a test naming today's columns would pass on the day it next
happens. Runs against a real migrated database, because the only
authority on which indexes exist is Postgres.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio

#: The operator class retrieval actually queries with. An index built for
#: a different one exists but is never used, which looks identical to
#: having no index at all.
EXPECTED_OPCLASS = "vector_cosine_ops"


async def _vector_columns(engine: AsyncEngine) -> list[tuple[str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT c.relname, a.attname "
                "FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_type t ON t.oid = a.atttypid "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "AND t.typname = 'vector' AND a.attnum > 0 "
                "ORDER BY c.relname, a.attname"
            )
        )
        return [(row[0], row[1]) for row in rows]


async def test_the_database_has_the_vector_columns_we_think_it_has(
    db_engine: AsyncEngine,
) -> None:
    """Guards the test below from silently passing on an empty list."""
    columns = await _vector_columns(db_engine)
    assert ("postmortems", "embedding") in columns
    assert ("architecture_decisions", "embedding") in columns
    assert ("ai_change_records", "embedding") in columns


async def test_every_vector_column_has_an_hnsw_cosine_index(
    db_engine: AsyncEngine,
) -> None:
    columns = await _vector_columns(db_engine)
    assert columns, "no vector columns found — the query above is wrong"

    unindexed = []
    async with db_engine.connect() as conn:
        for table, column in columns:
            definitions = [
                row[0]
                for row in await conn.execute(
                    sa.text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = :t"
                    ),
                    {"t": table},
                )
            ]
            matching = [
                definition
                for definition in definitions
                if "USING hnsw" in definition
                and f"{column} {EXPECTED_OPCLASS}" in definition
            ]
            if not matching:
                unindexed.append(f"{table}.{column}")

    assert not unindexed, (
        "vector column(s) with no HNSW "
        f"{EXPECTED_OPCLASS} index — these sequentially scan on every "
        f"similarity search: {unindexed}"
    )
