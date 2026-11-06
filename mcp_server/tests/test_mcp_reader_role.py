"""Least-privilege assertion for the `mcp-reader` role (Phase 24,
docs/AI_NATIVE_PLAN.md), same pattern every prior phase's own
role-scoped test already establishes (e.g.
api/tests/test_memory_api.py::test_api_reader_cannot_write_to_ai_change_records).

Runs api's own `alembic upgrade head` via subprocess against a fresh
testcontainers Postgres, not an in-process import -- mcp_server has no
Alembic of its own (Known Trap 1's "duplicate, don't cross-import"
reasoning extends to migrations too: this shells out to api's own venv,
the same pattern scripts/check_schema_drift.py already established for
cross-project schema concerns, rather than depending on api's
alembic.ini/migrations/ directly). This is deliberately the *only* test
file in this project that needs the real, fully-migrated schema with
real roles -- test_tools.py proves query-logic correctness against a
lighter `metadata.create_all` schema instead, matching worker/tests' own
established split between the two concerns.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Test-only values -- this container and every role in it are destroyed
#: at the end of the test session, so these never need to be real
#: secrets. Every migration under api/migrations/versions/ that reads a
#: role password via _require_env needs its own entry here, same as
#: api/tests/conftest.py's own _MIGRATION_ROLE_PASSWORDS.
_MIGRATION_ROLE_PASSWORDS = {
    "INGESTION_WRITER_PASSWORD": "test-ingestion-writer-password",
    "API_READER_PASSWORD": "test-api-reader-password",
    "INGEST_GATEWAY_DB_PASSWORD": "test-ingest-gateway-password",
    "ANOMALY_DETECTOR_DB_PASSWORD": "test-anomaly-detector-password",
    "CORRELATION_ENGINE_DB_PASSWORD": "test-correlation-engine-password",
    "ROOT_CAUSE_WRITER_DB_PASSWORD": "test-root-cause-writer-password",
    "REGISTRY_ADMIN_DB_PASSWORD": "test-registry-admin-password",
    "AUTH_SERVICE_DB_PASSWORD": "test-auth-service-password",
    "POSTMORTEM_WRITER_DB_PASSWORD": "test-postmortem-writer-password",
    "MCP_READER_DB_PASSWORD": "test-mcp-reader-password",
    # Phase 28. Every migration's `_require_env` must be satisfied for
    # `alembic upgrade head` to run at all, so a new role means a new
    # entry in all three copies of this list (here, api/tests/conftest.py,
    # scripts/check_migration_round_trip.py). That triplication is a real
    # smell and is recorded in docs/LIMITS.md rather than fixed here:
    # mcp_server is a separate uv project and cannot import api's
    # conftest, which is the same reason worker/app/db.py hand-mirrors
    # api's ORM.
    "FACT_WRITER_DB_PASSWORD": "test-fact-writer-password",
    # Phase 30: capture-writer, the eleventh role-creating migration's
    # password. Same triplication, same reason.
    "CAPTURE_WRITER_DB_PASSWORD": "test-capture-writer-password",
    "PROBE_WRITER_DB_PASSWORD": "test-probe-writer-password",
    "INVESTIGATION_WRITER_DB_PASSWORD": "test-investigation-writer-password",
    "AGENT_ADMIN_DB_PASSWORD": "test-agent-admin-password",
    "AGENT_REGISTRAR_DB_PASSWORD": "test-agent-registrar-password",
    "AGENT_GATEWAY_DB_PASSWORD": "test-agent-gateway-password",
}


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="module")
def mcp_reader_url(postgres_container: PostgresContainer) -> str:
    superuser_url = postgres_container.get_connection_url()
    env = {**os.environ, "DATABASE_URL": superuser_url, **_MIGRATION_ROLE_PASSWORDS}
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT / "api",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(postgres_container.port)
    dbname = postgres_container.dbname
    password = _MIGRATION_ROLE_PASSWORDS["MCP_READER_DB_PASSWORD"]
    return f"postgresql+asyncpg://mcp-reader:{password}@{host}:{port}/{dbname}"


@pytest.mark.parametrize(
    ("table", "insert_sql"),
    [
        ("postmortems", "INSERT INTO postmortems (title, body) VALUES ('x', 'y')"),
        (
            "architecture_decisions",
            "INSERT INTO architecture_decisions (title, body) VALUES ('x', 'y')",
        ),
        (
            "ai_change_records",
            "INSERT INTO ai_change_records (commit_sha, summary, committed_at) "
            "VALUES ('deadbeef', 'x', now())",
        ),
        (
            "invariant_violations",
            "INSERT INTO invariant_violations (invariant_name, message) "
            "VALUES ('coupled_files', 'x')",
        ),
        (
            "incident_change_links",
            "INSERT INTO incident_change_links "
            "(incident_id, ai_change_record_id, link_reason) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')",
        ),
        (
            "incident_candidates",
            "INSERT INTO incident_candidates (opened_at, last_anomaly_at, status) "
            "VALUES (now(), now(), 'open')",
        ),
        (
            "components",
            "INSERT INTO components (name) VALUES ('x')",
        ),
    ],
)
async def test_mcp_reader_cannot_write(mcp_reader_url: str, table: str, insert_sql: str) -> None:
    engine = create_async_engine(mcp_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(text(insert_sql))
    finally:
        await engine.dispose()


async def test_mcp_reader_can_select_every_granted_table(mcp_reader_url: str) -> None:
    """The positive half of least-privilege -- SELECT actually works on
    every table the migration grants it on, not just "writes fail"."""
    engine = create_async_engine(mcp_reader_url)
    try:
        async with engine.connect() as conn:
            for table in (
                "postmortems",
                "architecture_decisions",
                "ai_change_records",
                "invariant_violations",
                "incident_change_links",
                "incident_candidates",
                "anomalies",
                # Phase 27 renamed services -> components and replaced
                # service_dependencies with connections; 7c2e94b1f0aa
                # carries this role's SELECT across both, so the MCP
                # tools keep the reads they had.
                "components",
                "connections",
            ):
                await conn.execute(text(f"SELECT count(*) FROM {table}"))
    finally:
        await engine.dispose()
