"""Tests for app.memory.link_job (Phase 23, docs/AI_NATIVE_PLAN.md).

Two kinds of coverage:

- Pure-function tests for the service-name/file-path heuristic
  (_matching_file, _normalize_service_name) -- no DB needed, these
  operate on plain Python values.
- Integration tests for link_recent_changes itself, against a real
  Postgres+pgvector container (same justification as
  test_rag_retrieval.py's own docstring: the lookback-window boundary
  and the idempotent ON CONFLICT DO NOTHING behavior genuinely need a
  real database to prove correct, not a faked connection).

Schema created directly via SQLAlchemy's metadata.create_all against
app.db's own Core Table definitions, not through Alembic -- same
reasoning as test_rag_retrieval.py: worker has no migrations of its own,
and none of app.db's Core tables declare a ForeignKey, so create_all
needs nothing else present first. Because worker's Core mirrors don't
carry api's Alembic-side server_defaults (see app/db.py's own docstring:
"only enough shape to SELECT/INSERT/UPDATE"), every insert below supplies
every NOT NULL column explicitly, including `id`.
"""

import ast
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from app.db import (
    ai_change_records,
    incident_anomalies,
    incident_candidates,
    incident_change_links,
    metadata,
)
from app.memory.link_job import (
    AI_CHANGE_LOOKBACK,
    _matching_file,
    _normalize_service_name,
    link_recent_changes,
)
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

_INSERT_ANOMALY_SQL = text(
    "INSERT INTO anomalies "
    "(id, service_name, metric_name, score, threshold, detected_at, time_window) "
    "VALUES (:id, :service_name, :metric_name, :score, :threshold, :detected_at, "
    "tstzrange(:window_start, :window_end))"
)


# --- Pure heuristic (no DB) ----------------------------------------------


def test_normalize_service_name_converts_hyphens_to_underscores() -> None:
    assert _normalize_service_name("order-service") == "order_service"


def test_matching_file_positive_match() -> None:
    files = ["demo-services/order_service/main.py"]
    assert _matching_file("order-service", files) == "demo-services/order_service/main.py"


def test_matching_file_no_match_for_unrelated_service() -> None:
    files = ["demo-services/payments_service/main.py"]
    assert _matching_file("order-service", files) is None


def test_matching_file_empty_files_changed() -> None:
    assert _matching_file("order-service", []) is None


def test_matching_file_returns_first_match() -> None:
    files = [
        "README.md",
        "demo-services/order_service/main.py",
        "demo-services/order_service/db.py",
    ]
    assert _matching_file("order-service", files) == "demo-services/order_service/main.py"


# --- Structural: no app.rag / app.correlation import ----------------------


def test_link_job_never_imports_rag_or_correlation() -> None:
    """Same style as scripts/tests/test_no_llm_imports.py (Phase 22) --
    this job needs correlation's *output* (DB rows), never its *code*,
    and invariant 8/11 rule an LLM out of this module entirely."""
    path = Path(__file__).resolve().parent.parent / "app" / "memory" / "link_job.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("app.rag", "app.correlation")
    assert not any(name.startswith(f) for name in imported for f in forbidden)


# --- Integration (real Postgres) ------------------------------------------


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
        await setup_conn.run_sync(metadata.create_all)
        for table in (
            incident_change_links,
            incident_anomalies,
            ai_change_records,
            incident_candidates,
        ):
            await setup_conn.execute(delete(table))
        await setup_conn.execute(text("DELETE FROM anomalies"))

    yield eng
    await eng.dispose()


async def _insert_incident(conn: AsyncConnection, *, opened_at: datetime) -> uuid.UUID:
    incident_id = uuid.uuid4()
    await conn.execute(
        insert(incident_candidates).values(
            id=incident_id, opened_at=opened_at, last_anomaly_at=opened_at, status="open"
        )
    )
    return incident_id


async def _insert_anomaly_for_incident(
    conn: AsyncConnection, incident_id: uuid.UUID, *, service_name: str, detected_at: datetime
) -> None:
    anomaly_id = uuid.uuid4()
    await conn.execute(
        _INSERT_ANOMALY_SQL,
        {
            "id": anomaly_id,
            "service_name": service_name,
            "metric_name": "demo.http.server.duration",
            "score": 4.2,
            "threshold": 3.0,
            "detected_at": detected_at,
            "window_start": detected_at,
            "window_end": detected_at,
        },
    )
    await conn.execute(
        insert(incident_anomalies).values(incident_id=incident_id, anomaly_id=anomaly_id)
    )


async def _insert_change_record(
    conn: AsyncConnection, *, files_changed: list[str], committed_at: datetime
) -> uuid.UUID:
    record_id = uuid.uuid4()
    await conn.execute(
        insert(ai_change_records).values(
            id=record_id,
            commit_sha=uuid.uuid4().hex,
            summary="A commit",
            files_changed=files_changed,
            committed_at=committed_at,
        )
    )
    return record_id


async def _links_for(conn: AsyncConnection, incident_id: uuid.UUID) -> list:
    rows = (
        await conn.execute(
            select(incident_change_links).where(incident_change_links.c.incident_id == incident_id)
        )
    ).all()
    return list(rows)


@pytest.mark.asyncio
async def test_positive_match_creates_link(engine: AsyncEngine) -> None:
    opened_at = datetime.now(UTC)
    committed_at = opened_at - timedelta(minutes=14)
    async with engine.begin() as conn:
        incident_id = await _insert_incident(conn, opened_at=opened_at)
        await _insert_anomaly_for_incident(
            conn, incident_id, service_name="order-service", detected_at=opened_at
        )
        record_id = await _insert_change_record(
            conn,
            files_changed=["demo-services/order_service/main.py"],
            committed_at=committed_at,
        )

    result = await link_recent_changes({"correlation_engine": engine})
    assert result["links_created"] == 1

    async with engine.connect() as conn:
        links = await _links_for(conn, incident_id)
    assert len(links) == 1
    assert links[0].ai_change_record_id == record_id
    assert "order-service" in links[0].link_reason
    assert "demo-services/order_service/main.py" in links[0].link_reason


@pytest.mark.asyncio
async def test_no_change_record_in_window_creates_no_link(engine: AsyncEngine) -> None:
    opened_at = datetime.now(UTC)
    async with engine.begin() as conn:
        incident_id = await _insert_incident(conn, opened_at=opened_at)
        await _insert_anomaly_for_incident(
            conn, incident_id, service_name="order-service", detected_at=opened_at
        )
        # A record that exists but far outside the lookback window.
        await _insert_change_record(
            conn,
            files_changed=["demo-services/order_service/main.py"],
            committed_at=opened_at - timedelta(hours=2),
        )

    result = await link_recent_changes({"correlation_engine": engine})
    assert result["links_created"] == 0

    async with engine.connect() as conn:
        links = await _links_for(conn, incident_id)
    assert links == []


@pytest.mark.asyncio
async def test_unrelated_service_change_creates_no_link(engine: AsyncEngine) -> None:
    """The actual discriminating test for the heuristic -- a change
    record exists, is well within the lookback window, but touches a
    different service's files entirely."""
    opened_at = datetime.now(UTC)
    async with engine.begin() as conn:
        incident_id = await _insert_incident(conn, opened_at=opened_at)
        await _insert_anomaly_for_incident(
            conn, incident_id, service_name="order-service", detected_at=opened_at
        )
        await _insert_change_record(
            conn,
            files_changed=["demo-services/payments_service/main.py"],
            committed_at=opened_at - timedelta(minutes=5),
        )

    result = await link_recent_changes({"correlation_engine": engine})
    assert result["links_created"] == 0

    async with engine.connect() as conn:
        links = await _links_for(conn, incident_id)
    assert links == []


@pytest.mark.asyncio
async def test_lookback_window_boundary(engine: AsyncEngine) -> None:
    """Exactly AI_CHANGE_LOOKBACK before opened_at links; one second
    further back doesn't -- mirrors
    test_correlation_graph.py::test_exactly_at_window_boundary_links'
    own inclusive-boundary convention for the analogous correlation
    window."""
    opened_at = datetime.now(UTC)
    async with engine.begin() as conn:
        incident_id = await _insert_incident(conn, opened_at=opened_at)
        await _insert_anomaly_for_incident(
            conn, incident_id, service_name="order-service", detected_at=opened_at
        )
        inside_id = await _insert_change_record(
            conn,
            files_changed=["demo-services/order_service/main.py"],
            committed_at=opened_at - AI_CHANGE_LOOKBACK,
        )
        await _insert_change_record(
            conn,
            files_changed=["demo-services/order_service/main.py"],
            committed_at=opened_at - AI_CHANGE_LOOKBACK - timedelta(seconds=1),
        )

    await link_recent_changes({"correlation_engine": engine})

    async with engine.connect() as conn:
        links = await _links_for(conn, incident_id)
    assert len(links) == 1
    assert links[0].ai_change_record_id == inside_id


@pytest.mark.asyncio
async def test_rerun_is_idempotent(engine: AsyncEngine) -> None:
    """Trap 3: an incident re-scanned across many ticks must not get
    re-linked to the same change record repeatedly."""
    opened_at = datetime.now(UTC)
    async with engine.begin() as conn:
        incident_id = await _insert_incident(conn, opened_at=opened_at)
        await _insert_anomaly_for_incident(
            conn, incident_id, service_name="order-service", detected_at=opened_at
        )
        await _insert_change_record(
            conn,
            files_changed=["demo-services/order_service/main.py"],
            committed_at=opened_at - timedelta(minutes=10),
        )

    first = await link_recent_changes({"correlation_engine": engine})
    second = await link_recent_changes({"correlation_engine": engine})
    assert first["links_created"] == 1
    assert second["links_created"] == 0

    async with engine.connect() as conn:
        links = await _links_for(conn, incident_id)
    assert len(links) == 1
