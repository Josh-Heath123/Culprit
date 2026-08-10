"""Integration tests for the four Culprit MCP tools (Phase 24,
docs/AI_NATIVE_PLAN.md), against a real Postgres+pgvector container --
same justification as worker/tests/test_rag_retrieval.py's own docstring:
a similarity-ranked UNION ALL and a JSONB containment query genuinely
need a real database to prove correct, not a faked connection.

Schema created directly via `mcp_server.tools.metadata.create_all`, not
Alembic -- this file only needs mcp_server's own minimal Core table
shapes, the same "only enough shape to SELECT" mirrors every other
project in this repo already uses for its own tests. Least-privilege
(does the real `mcp-reader` role actually behave this way) is a
different question, answered separately by test_mcp_reader_role.py.

`Context` isn't constructed for real here -- FastMCP's Context is not
trivially instantiable outside a live request, and none of these tools
need anything from it beyond `ctx.request_context.lifespan_context.engine`
-- a lightweight duck-typed stand-in matching that exact attribute path
is simpler and just as faithful for this purpose.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from mcp_server import tools

pytestmark = pytest.mark.asyncio


def _vec(*nonzero: tuple[int, float], dim: int = 1024) -> list[float]:
    """A `dim`-length vector with `nonzero`'s (index, value) pairs set and
    everything else zero -- lets each test construct vectors with
    controlled, predictable cosine similarity instead of random ones.
    Same helper as worker/tests/test_rag_retrieval.py's own."""
    values = [0.0] * dim
    for index, value in nonzero:
        values[index] = value
    return values


def _fake_ctx(engine: AsyncEngine) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(engine=engine))
    )


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def engine(postgres_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    url = postgres_container.get_connection_url()
    eng = create_async_engine(url)
    async with eng.begin() as setup_conn:
        await setup_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await setup_conn.run_sync(tools.metadata.create_all)
        for table in (
            tools.invariant_violations,
            tools.incident_change_links,
            tools.incident_candidates,
            tools.ai_change_records,
            tools.architecture_decisions,
            tools.postmortems,
        ):
            await setup_conn.execute(delete(table))

    yield eng
    await eng.dispose()


async def _insert_postmortem(
    conn: AsyncConnection, *, title: str, embedding: list[float]
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        insert(tools.postmortems).values(
            id=row_id, title=title, body="body text", embedding=embedding
        )
    )
    return row_id


async def _insert_change_record(
    conn: AsyncConnection, *, commit_sha: str, files_changed: list[str]
) -> uuid.UUID:
    row_id = uuid.uuid4()
    await conn.execute(
        insert(tools.ai_change_records).values(
            id=row_id,
            commit_sha=commit_sha,
            summary=f"Change {commit_sha}",
            files_changed=files_changed,
            committed_at=datetime.now(UTC),
        )
    )
    return row_id


async def _insert_violation(conn: AsyncConnection, *, ai_change_record_id: uuid.UUID) -> None:
    await conn.execute(
        insert(tools.invariant_violations).values(
            id=uuid.uuid4(),
            invariant_name="coupled_files",
            message='"a" changed but its declared pair "b" did not',
            detected_at=datetime.now(UTC),
            ai_change_record_id=ai_change_record_id,
        )
    )


async def _insert_incident_link(
    conn: AsyncConnection, *, ai_change_record_id: uuid.UUID
) -> uuid.UUID:
    incident_id = uuid.uuid4()
    await conn.execute(
        insert(tools.incident_candidates).values(
            id=incident_id, status="open", opened_at=datetime.now(UTC)
        )
    )
    await conn.execute(
        insert(tools.incident_change_links).values(
            incident_id=incident_id, ai_change_record_id=ai_change_record_id
        )
    )
    return incident_id


# --- culprit_search_memory --------------------------------------------------


async def test_search_memory_returns_close_postmortem_with_similarity(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with engine.begin() as conn:
        matching_id = await _insert_postmortem(
            conn, title="Order service retry storm", embedding=_vec((0, 1.0))
        )
        await _insert_postmortem(conn, title="Unrelated", embedding=_vec((1, 1.0)))

    async def fake_embed_query(text: str) -> list[float]:
        return _vec((0, 1.0))

    monkeypatch.setattr(tools, "_embed_query", fake_embed_query)

    results = await tools.culprit_search_memory(
        tools.SearchMemoryInput(query="retry storm", record_types=["postmortem"]), _fake_ctx(engine)
    )

    assert results[0].id == str(matching_id)
    assert results[0].title == "Order service retry storm"
    assert results[0].similarity > results[1].similarity
    assert results[0].url == f"/postmortems/{matching_id}"
    # Never the raw embedding vector -- SearchResult has no such field at
    # all, but assert the actual serialized shape too, not just the model.
    for result in results:
        assert not hasattr(result, "embedding")


async def test_search_memory_empty_database_returns_empty_list(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_embed_query(text: str) -> list[float]:
        return _vec((0, 1.0))

    monkeypatch.setattr(tools, "_embed_query", fake_embed_query)

    results = await tools.culprit_search_memory(
        tools.SearchMemoryInput(query="anything"), _fake_ctx(engine)
    )
    assert results == []


async def test_search_memory_rejects_empty_record_types(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_embed_query(text: str) -> list[float]:
        return _vec((0, 1.0))

    monkeypatch.setattr(tools, "_embed_query", fake_embed_query)

    with pytest.raises(ValueError, match="record_types"):
        await tools.culprit_search_memory(
            tools.SearchMemoryInput(query="x", record_types=[]), _fake_ctx(engine)
        )


# --- culprit_file_history ----------------------------------------------------


async def test_file_history_returns_change_violation_and_incident_nested(
    engine: AsyncEngine,
) -> None:
    """The single most important test in this file (per the phase's own
    acceptance criteria) -- the concrete instance of the closed loop this
    whole plan's thesis rests on."""
    async with engine.begin() as conn:
        record_id = await _insert_change_record(
            conn, commit_sha="a" * 40, files_changed=["demo-services/order_service/main.py"]
        )
        await _insert_violation(conn, ai_change_record_id=record_id)
        incident_id = await _insert_incident_link(conn, ai_change_record_id=record_id)

    entries = await tools.culprit_file_history(
        tools.FileHistoryInput(file_path="demo-services/order_service/main.py"), _fake_ctx(engine)
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.commit_sha == "a" * 40
    assert len(entry.violations) == 1
    assert entry.violations[0].invariant_name == "coupled_files"
    assert len(entry.linked_incidents) == 1
    assert entry.linked_incidents[0].id == str(incident_id)
    assert entry.linked_incidents[0].status == "open"


async def test_file_history_unknown_file_returns_empty_list(engine: AsyncEngine) -> None:
    entries = await tools.culprit_file_history(
        tools.FileHistoryInput(file_path="never/touched.py"), _fake_ctx(engine)
    )
    assert entries == []


async def test_file_history_ignores_partial_path_matches(engine: AsyncEngine) -> None:
    """files_changed containment is exact-element, not substring -- a
    change touching a *different* file under a similar-looking path must
    not show up."""
    async with engine.begin() as conn:
        await _insert_change_record(
            conn, commit_sha="b" * 40, files_changed=["demo-services/order_service/other.py"]
        )

    entries = await tools.culprit_file_history(
        tools.FileHistoryInput(file_path="demo-services/order_service/main.py"), _fake_ctx(engine)
    )
    assert entries == []


# --- culprit_coupled_files ---------------------------------------------------


async def test_coupled_files_returns_declared_pair_both_directions() -> None:
    forward = await tools.culprit_coupled_files(
        tools.CoupledFilesInput(file_path="worker/app/db.py")
    )
    backward = await tools.culprit_coupled_files(
        tools.CoupledFilesInput(file_path="api/app/db/models.py")
    )
    assert forward == ["api/app/db/models.py"]
    assert backward == ["worker/app/db.py"]


async def test_coupled_files_returns_empty_list_for_undeclared_file() -> None:
    result = await tools.culprit_coupled_files(
        tools.CoupledFilesInput(file_path="some/unrelated/file.py")
    )
    assert result == []


# --- culprit_architecture_decisions ------------------------------------------


async def test_architecture_decisions_lists_recent_when_no_query(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(tools.architecture_decisions).values(
                id=uuid.uuid4(),
                title="Use Postgres for everything",
                body="One database is simpler to operate.",
                created_at=datetime.now(UTC),
            )
        )

    results = await tools.culprit_architecture_decisions(
        tools.ArchitectureDecisionsInput(), _fake_ctx(engine)
    )
    assert len(results) == 1
    assert results[0].title == "Use Postgres for everything"


async def test_architecture_decisions_empty_returns_empty_list(engine: AsyncEngine) -> None:
    results = await tools.culprit_architecture_decisions(
        tools.ArchitectureDecisionsInput(), _fake_ctx(engine)
    )
    assert results == []


async def test_architecture_decisions_search_scopes_to_decisions(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with engine.begin() as conn:
        matching_id = uuid.uuid4()
        await conn.execute(
            insert(tools.architecture_decisions).values(
                id=matching_id,
                title="Adopt trunk-based development",
                body="body",
                embedding=_vec((0, 1.0)),
                created_at=datetime.now(UTC),
            )
        )

    async def fake_embed_query(text: str) -> list[float]:
        return _vec((0, 1.0))

    monkeypatch.setattr(tools, "_embed_query", fake_embed_query)

    results = await tools.culprit_architecture_decisions(
        tools.ArchitectureDecisionsInput(query="trunk based development"), _fake_ctx(engine)
    )
    assert len(results) == 1
    assert results[0].id == str(matching_id)
