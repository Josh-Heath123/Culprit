# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""F44-041 (Phase 44 batch 3): "planted or real, never both" becomes a
constraint, in a new migration, d1e5b9c3a7f2.

Two databases, each in its own container, as test_model_migration.py does:
one whose verifications already record an investigation both ways, which
the migration must refuse to change, saying how many and what to do, with
every row left as it was; and one that upgrades, refuses a second label,
and goes down and up again.
"""

import asyncio
import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

BEFORE = "a6c2e9d4f8b1"
AFTER = "d1e5b9c3a7f2"


def _insert(investigation: str, verification: str, source: str) -> str:
    return (
        "INSERT INTO verifications (id, investigation_id, environment, verdict, "
        "failing_now_passes, no_regressions, changes_explained, verified_at, source, "
        f"submitted_by, verification, ingested_at) VALUES ('{verification}', '{investigation}', "
        f"'e', 'not_resolved', false, true, true, now(), '{source}', 'project-token', '{{}}', "
        "now())"
    )


def _investigation(name: str) -> str:
    return (
        "INSERT INTO investigations (id, opened_at, environment, symptom) VALUES "
        f"('{name}', now(), 'e', '{{}}')"
    )


async def _run(url: str, *statements: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(sa.text(statement))
    finally:
        await engine.dispose()


async def _rows(url: str) -> list[tuple]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                sa.text("SELECT id, investigation_id, source FROM verifications ORDER BY id")
            )
            return [tuple(row) for row in result]
    finally:
        await engine.dispose()


@pytest.fixture
def container(migration_role_passwords: dict[str, str]) -> Iterator[str]:
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        os.environ["DATABASE_URL"] = url
        os.environ.update(migration_role_passwords)
        yield url


def test_the_migration_refuses_rows_recorded_both_ways_and_changes_none(
    container: str, alembic_ini: str
) -> None:
    command.upgrade(Config(alembic_ini), BEFORE)
    asyncio.run(
        _run(
            container,
            _investigation("inv-both"),
            _investigation("inv-one"),
            _insert("inv-both", "ver-0000000000000001", "planted"),
            _insert("inv-both", "ver-0000000000000002", "real"),
            _insert("inv-one", "ver-0000000000000003", "real"),
        )
    )
    before = asyncio.run(_rows(container))

    with pytest.raises(RuntimeError) as refused:
        command.upgrade(Config(alembic_ini), AFTER)

    message = str(refused.value)
    assert "1 investigation" in message, message
    assert "planted and real" in message
    assert "GROUP BY investigation_id" in message  # how to list them
    assert asyncio.run(_rows(container)) == before


def test_the_constraint_refuses_a_second_label_and_goes_down_and_up(
    container: str, alembic_ini: str
) -> None:
    command.upgrade(Config(alembic_ini), BEFORE)
    asyncio.run(
        _run(
            container,
            _investigation("inv-a"),
            _insert("inv-a", "ver-0000000000000001", "planted"),
        )
    )
    command.upgrade(Config(alembic_ini), AFTER)

    # The same label again is fine; the other is refused by the database.
    asyncio.run(_run(container, _insert("inv-a", "ver-0000000000000002", "planted")))
    with pytest.raises(DBAPIError, match="ex_verifications_one_source"):
        asyncio.run(_run(container, _insert("inv-a", "ver-0000000000000003", "real")))

    command.downgrade(Config(alembic_ini), BEFORE)
    asyncio.run(_run(container, _insert("inv-a", "ver-0000000000000004", "planted")))
    command.upgrade(Config(alembic_ini), AFTER)
    assert [row[0] for row in asyncio.run(_rows(container))] == [
        "ver-0000000000000001",
        "ver-0000000000000002",
        "ver-0000000000000004",
    ]
