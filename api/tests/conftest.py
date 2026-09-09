"""Loads api/.env before any test module is collected — some modules
(e.g. app/auth/config.py) read required env vars at import time, and
conftest.py is guaranteed to run before pytest imports test files in
whatever order it discovers them, unlike relying on one test file's own
imports (e.g. app.main's own load_dotenv() call) happening to run first.

Phase 14 adds the first real integration tests to this suite
(test_registry_api.py, test_ingest_gateway_key_refresh.py) — the
fixtures below back those. They're lazy: nothing here starts a
container until a test actually requests `migrated_database_url` (or a
fixture that depends on it), so pure-unit test modules like test_auth.py
never pay for Docker/Postgres at all.
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

load_dotenv()

#: Import-time-required variables, defaulted here so `just test` works on
#: a clean checkout with no api/.env. Phase 26 removed the fail-open
#: `<role>-dev-password` fallbacks these used to have inside
#: app/*/config.py (see app/env.py): refusing to start without them is
#: the point, so the values have to come from somewhere, and a test
#: harness is the right somewhere. `setdefault`, not assignment, so a
#: real api/.env or a CI-provided value always wins.
#:
#: These are not connection strings anything connects with — every test
#: that touches a database goes through `migrated_database_url` /
#: `role_database_url` below, against a throwaway container. They exist
#: only to satisfy reads that happen at module import.
_IMPORT_TIME_DEFAULTS = {
    "JWT_SECRET_KEY": "test-jwt-secret-not-a-real-secret",
    "AGENT_AUTOMATION_TOKEN": "dev-agent-automation-token",
    "INGEST_GATEWAY_DATABASE_URL": "postgresql+asyncpg://ingest-gateway:test@localhost:5432/test",
    "API_READER_DATABASE_URL": "postgresql+asyncpg://api-reader:test@localhost:5432/test",
    "REGISTRY_ADMIN_DATABASE_URL": "postgresql+asyncpg://registry-admin:test@localhost:5432/test",
    "AUTH_SERVICE_DATABASE_URL": "postgresql+asyncpg://auth-service:test@localhost:5432/test",
    "POSTMORTEM_WRITER_DATABASE_URL": (
        "postgresql+asyncpg://postmortem-writer:test@localhost:5432/test"
    ),
}
for _name, _value in _IMPORT_TIME_DEFAULTS.items():
    os.environ.setdefault(_name, _value)

_ALEMBIC_INI = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")

#: Role passwords the migrations under api/migrations/versions/ read via
#: _require_env at upgrade time (e.g. a0cac3233f8d_create_correlation_engine_role.py,
#: 635870479f4e_create_service_registry.py). Test-only values — this
#: container and every role in it are destroyed at the end of the test
#: session, so these never need to be real secrets.
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
}


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    # Same image infra/docker-compose.yml uses locally (timescaledb-ha
    # bundles both the timescaledb and pgvector extensions the very first
    # migration, e3f8d40026c9, creates) — a plain postgres:16 image would
    # fail on `CREATE EXTENSION timescaledb`.
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def migrated_database_url(postgres_container: PostgresContainer) -> str:
    """Runs `alembic upgrade head` once per test session against a fresh
    container — deliberately a *fresh* install (none of the demo
    ORDER_SERVICE_API_KEY/etc. env vars set), not a copy of culprit.co.za's
    own seeded database: 48c0b29fa215's Phase-14 loosening (see that
    migration's own docstring) makes a fresh install with zero demo keys
    a fully real, supported path now, and the tests using this fixture
    create whatever services/keys they need themselves rather than
    relying on demo seed data that may or may not exist.

    Sets DATABASE_URL and every role password as real process env vars
    (not just local variables) because alembic/env.py and several
    app.*.config modules read os.environ directly at import/run time —
    see this module's own docstring on why that ordering matters.
    """
    url = postgres_container.get_connection_url()  # postgresql+asyncpg://...

    os.environ["DATABASE_URL"] = url
    os.environ.update(_MIGRATION_ROLE_PASSWORDS)

    command.upgrade(Config(_ALEMBIC_INI), "head")

    return url


@pytest_asyncio.fixture(scope="session")
async def db_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """A superuser engine against the migrated container — test setup/
    teardown helpers (inserting fixture rows, truncating between tests)
    use this directly rather than going through any of the
    least-privilege role engines the app itself uses."""
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def role_database_url(
    postgres_container: PostgresContainer, migrated_database_url: str
) -> Callable[[str, str], str]:
    """Builds a connection URL for one of the least-privilege roles a
    migration created (api-reader, registry-admin, ingest-gateway, ...),
    using the container's own host/port/dbname and the matching test
    password from _MIGRATION_ROLE_PASSWORDS — so tests exercise the same
    role a real request would run under in production, not the
    container's superuser. `migrated_database_url` is an unused
    parameter beyond ordering: it guarantees the roles already exist by
    the time this is called."""
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(postgres_container.port)
    dbname = postgres_container.dbname

    def build(role: str, password_env: str) -> str:
        password = _MIGRATION_ROLE_PASSWORDS[password_env]
        return f"postgresql+asyncpg://{role}:{password}@{host}:{port}/{dbname}"

    return build
