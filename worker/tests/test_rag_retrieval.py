"""Integration tests for retrieve_similar_records (Phase 21,
docs/AI_NATIVE_PLAN.md) and a light regression check on
retrieve_similar_postmortems (Phase 6, untouched) — against a real
Postgres+pgvector container, the first worker test to use one (every
other test in this directory is a pure unit test, per this project's own
established convention — see test_embed_job.py's own docstring). A
UNION ALL query across three tables using pgvector's cosine_distance
operator genuinely needs a real database to prove correct; faking SQL
execution for a query this shape would validate nothing real.

Schema created directly via SQLAlchemy's metadata.create_all against
app.db's own Core Table definitions, not through Alembic — worker has no
migrations of its own, and invoking api's Alembic config from worker's
test suite would be real cross-project coupling for no benefit here,
since this test isn't exercising role/grant access control (that's
api/tests/test_memory_api.py's job), just query correctness against a
plain superuser connection testcontainers already provides. None of
worker/app/db.py's Core tables declare a ForeignKey, so create_all needs
nothing else present first.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from app.db import ai_change_records, architecture_decisions, metadata, postmortems
from app.rag.retrieval import retrieve_similar_postmortems, retrieve_similar_records
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.asyncio


def _vec(*nonzero: tuple[int, float], dim: int = 1024) -> list[float]:
    """A `dim`-length vector with `nonzero`'s (index, value) pairs set and
    everything else zero -- lets each test construct vectors with
    controlled, predictable cosine similarity instead of random ones."""
    values = [0.0] * dim
    for index, value in nonzero:
        values[index] = value
    return values


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def conn(postgres_container: PostgresContainer) -> AsyncIterator[AsyncConnection]:
    # already postgresql+asyncpg://... thanks to driver="asyncpg" above
    url = postgres_container.get_connection_url()
    engine = create_async_engine(url)
    async with engine.begin() as setup_conn:
        await setup_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await setup_conn.run_sync(metadata.create_all)
        # the container (and its schema) is module-scoped for speed, but each
        # test needs a clean slate -- otherwise rows from an earlier test in
        # this module leak into a later test's query results.
        for table in (postmortems, architecture_decisions, ai_change_records):
            await setup_conn.execute(delete(table))

    connection = await engine.connect()
    try:
        yield connection
    finally:
        await connection.close()
        await engine.dispose()


async def _insert_postmortem(conn: AsyncConnection, *, embedding: list[float] | None) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        insert(postmortems).values(
            id=row_id,
            title="Postmortem",
            body="A past incident writeup.",
            embedding=embedding,
            incident_candidate_id=None,
            created_at=datetime.now(UTC),
        )
    )
    return row_id


async def _insert_decision(conn: AsyncConnection, *, embedding: list[float] | None) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        insert(architecture_decisions).values(
            id=row_id,
            title="Decision",
            body="Use Postgres for everything.",
            embedding=embedding,
            created_at=datetime.now(UTC),
        )
    )
    return row_id


async def _insert_change_record(
    conn: AsyncConnection, *, embedding: list[float] | None
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        insert(ai_change_records).values(
            id=row_id,
            commit_sha=uuid.uuid4().hex,
            summary="Fix the flaky retry test.",
            embedding=embedding,
            committed_at=datetime.now(UTC),
        )
    )
    return row_id


async def test_retrieve_similar_records_ranks_across_all_three_tables(
    conn: AsyncConnection,
) -> None:
    query = _vec((0, 1.0))
    postmortem_id = await _insert_postmortem(conn, embedding=_vec((0, 1.0)))  # identical
    decision_id = await _insert_decision(conn, embedding=_vec((0, 0.9), (1, 0.1)))  # close
    change_id = await _insert_change_record(conn, embedding=_vec((1, 1.0)))  # orthogonal
    await conn.commit()

    results = await retrieve_similar_records(conn, query, top_k=3)

    assert [r.record_type for r in results] == ["postmortem", "decision", "ai_change"]
    assert [r.id for r in results] == [postmortem_id, decision_id, change_id]
    assert results[0].similarity > results[1].similarity > results[2].similarity


async def test_retrieve_similar_records_filters_by_record_types(conn: AsyncConnection) -> None:
    query = _vec((0, 1.0))
    postmortem_id = await _insert_postmortem(conn, embedding=_vec((0, 1.0)))
    decision_id = await _insert_decision(conn, embedding=_vec((0, 0.9), (1, 0.1)))
    await _insert_change_record(conn, embedding=_vec((1, 1.0)))
    await conn.commit()

    results = await retrieve_similar_records(
        conn, query, top_k=5, record_types=["postmortem", "decision"]
    )

    assert {r.id for r in results} == {postmortem_id, decision_id}
    assert all(r.record_type != "ai_change" for r in results)


async def test_retrieve_similar_records_narrowed_to_one_type(conn: AsyncConnection) -> None:
    query = _vec((0, 1.0))
    await _insert_postmortem(conn, embedding=_vec((0, 1.0)))
    decision_id = await _insert_decision(conn, embedding=_vec((0, 1.0)))
    await conn.commit()

    results = await retrieve_similar_records(conn, query, record_types=["decision"])

    assert [r.id for r in results] == [decision_id]


async def test_retrieve_similar_records_excludes_pending_rows(conn: AsyncConnection) -> None:
    query = _vec((0, 1.0))
    embedded_id = await _insert_postmortem(conn, embedding=_vec((0, 1.0)))
    await _insert_postmortem(conn, embedding=None)  # still pending -- must not appear
    await conn.commit()

    results = await retrieve_similar_records(conn, query, record_types=["postmortem"])

    assert [r.id for r in results] == [embedded_id]


async def test_retrieve_similar_records_ai_change_uses_commit_sha_as_title(
    conn: AsyncConnection,
) -> None:
    query = _vec((0, 1.0))
    row_id = uuid.uuid4()
    await conn.execute(
        insert(ai_change_records).values(
            id=row_id,
            commit_sha="deadbeef" * 5,
            summary="A commit message.",
            embedding=_vec((0, 1.0)),
            committed_at=datetime.now(UTC),
        )
    )
    await conn.commit()

    results = await retrieve_similar_records(conn, query, record_types=["ai_change"])

    assert results[0].title == "deadbeef" * 5
    assert results[0].body == "A commit message."


async def test_retrieve_similar_records_rejects_empty_record_types(conn: AsyncConnection) -> None:
    with pytest.raises(ValueError, match="record_types"):
        await retrieve_similar_records(conn, _vec((0, 1.0)), record_types=[])


async def test_retrieve_similar_postmortems_still_works_unchanged(conn: AsyncConnection) -> None:
    """Phase 21 leaves this function alone (invariant 11) -- a light
    regression check, not a full re-test of Phase 6's own coverage."""
    query = _vec((0, 1.0))
    postmortem_id = await _insert_postmortem(conn, embedding=_vec((0, 1.0)))
    await conn.commit()

    results = await retrieve_similar_postmortems(conn, query)

    assert [r.id for r in results] == [postmortem_id]
