"""Phase 27 field 13: the data migration, from a populated Phase-26
database.

Phase 27's first acceptance criterion is *"an existing deployment
upgrades with no service/dependency data loss"*. The only way to check
that is to build a database that looks like a real pre-Phase-27
deployment — services, their dependency edges, their API keys, and the
GRANTs the role model depends on — then run the migration over it and
look at what came out.

So this module does not use the session-scoped `migrated_database_url`
fixture. It stands up its own container, migrates to `a3d81f6c4b27`
(Phase 26.1, the revision before this one), inserts data, and only then
upgrades. Migrating to head first and inserting afterwards would test
nothing: the rows would already be in the new shape.

Everything goes through raw SQL on an asyncpg engine rather than the ORM.
The ORM describes the schema *after* this migration, so using it to
populate the *before* state would be circular — and the claim being
checked is about what the database holds, not about what SQLAlchemy
thinks it holds.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

pytestmark = pytest.mark.asyncio

#: The revision immediately before Phase 27's — a database in the state a
#: real deployment running Phase 26.1 would be in.
BEFORE = "a3d81f6c4b27"
AFTER = "7c2e94b1f0aa"

#: The exact topology `infra/demo-services.yaml` produced before this
#: phase, so "no data loss" is checked against the shape a real
#: deployment actually has rather than a convenient one.
_LEGACY_SERVICES = (
    ("order-service", "Order Service"),
    ("inventory-service", "Inventory Service"),
    ("payments-service", "Payments Service"),
)
_LEGACY_EDGES = (
    ("order-service", "inventory-service"),
    ("order-service", "payments-service"),
    ("inventory-service", "order-service"),
    ("payments-service", "order-service"),
)


@pytest.fixture(scope="module")
def upgraded_url(alembic_ini: str, migration_role_passwords: dict[str, str]) -> Iterator[str]:
    """A throwaway container taken through the whole story: migrate to
    `BEFORE`, populate it like a real deployment, then run Phase 27's
    migration over it.

    Synchronous on purpose. `alembic upgrade` calls `asyncio.run`
    internally (see api/migrations/env.py), which raises inside a running
    event loop — so both upgrades and the seeding in between have to
    happen outside one. asyncpg, not psycopg2: it is the only Postgres
    driver this project installs (api/pyproject.toml).
    """
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        url = container.get_connection_url()
        # alembic/env.py and the role-creating migrations read these from
        # the process environment.
        os.environ["DATABASE_URL"] = url
        os.environ.update(migration_role_passwords)

        command.upgrade(Config(alembic_ini), BEFORE)
        asyncio.run(_seed_legacy_registry(url))
        command.upgrade(Config(alembic_ini), AFTER)
        yield url


@pytest_asyncio.fixture(scope="module")
async def upgraded_engine(upgraded_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(upgraded_url)
    yield engine
    await engine.dispose()


async def _seed_legacy_registry(url: str) -> None:
    engine = create_async_engine(url)
    try:
        await _insert_legacy_rows(engine)
    finally:
        await engine.dispose()


async def _insert_legacy_rows(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for name, display in _LEGACY_SERVICES:
            await conn.execute(
                sa.text(
                    "INSERT INTO services (name, display_name, sort_order, monitored_metrics) "
                    "VALUES (:name, :display, 0, '[]'::jsonb)"
                ),
                {"name": name, "display": display},
            )
        for source, target in _LEGACY_EDGES:
            await conn.execute(
                sa.text(
                    "INSERT INTO service_dependencies (from_service_id, to_service_id) "
                    "SELECT f.id, t.id FROM services f, services t "
                    "WHERE f.name = :source AND t.name = :target"
                ),
                {"source": source, "target": target},
            )
        await conn.execute(
            sa.text(
                "INSERT INTO api_keys (service_name, service_id, key_hash, label) "
                "SELECT s.name, s.id, 'hash-' || s.name, 'initial' FROM services s"
            )
        )


async def _scalar(engine: AsyncEngine, sql: str):
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql))).scalar_one()


# --- acceptance criterion 1: no data loss -----------------------------


async def test_every_service_survives_as_a_component(upgraded_engine: AsyncEngine) -> None:
    async with upgraded_engine.connect() as conn:
        names = set((await conn.execute(sa.text("SELECT name FROM components"))).scalars())
    assert names == {name for name, _ in _LEGACY_SERVICES}


async def test_display_names_survive(upgraded_engine: AsyncEngine) -> None:
    async with upgraded_engine.connect() as conn:
        rows = set(
            (await conn.execute(sa.text("SELECT name, display_name FROM components"))).all()
        )
    assert rows == set(_LEGACY_SERVICES)


async def test_every_dependency_survives_as_a_connection(upgraded_engine: AsyncEngine) -> None:
    async with upgraded_engine.connect() as conn:
        edges = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT f.name, t.name, c.kind FROM connections c "
                        "JOIN components f ON f.id = c.from_component_id "
                        "JOIN components t ON t.id = c.to_component_id"
                    )
                )
            ).all()
        )
    assert edges == {(source, target, "http") for source, target in _LEGACY_EDGES}


async def test_migrated_connections_are_declared_not_inferred(
    upgraded_engine: AsyncEngine,
) -> None:
    """`service_dependencies` recorded no provenance, and every row in it
    got there because a human declared it — so `culprit_yaml` is the true
    answer. `criticality` is honestly `unknown`: nothing ever classified
    these edges, and a flattering guess of `on_request_path` would be a
    fabrication the severity computation in Phase 29 would then trust."""
    async with upgraded_engine.connect() as conn:
        rows = set(
            (
                await conn.execute(
                    sa.text("SELECT DISTINCT declared_by, criticality FROM connections")
                )
            ).all()
        )
    assert rows == {("culprit_yaml", "unknown")}


async def test_api_keys_still_point_at_their_component(upgraded_engine: AsyncEngine) -> None:
    """The FK followed the rename. This is the check that would have
    failed had the migration created a new table and copied rows."""
    orphaned = await _scalar(
        upgraded_engine,
        "SELECT count(*) FROM api_keys k "
        "LEFT JOIN components c ON c.id = k.service_id WHERE c.id IS NULL",
    )
    total = await _scalar(upgraded_engine, "SELECT count(*) FROM api_keys")
    assert (total, orphaned) == (len(_LEGACY_SERVICES), 0)


async def test_the_old_tables_are_gone(upgraded_engine: AsyncEngine) -> None:
    remaining = await _scalar(
        upgraded_engine,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "AND table_name IN ('services', 'service_dependencies')",
    )
    assert remaining == 0


# --- least privilege --------------------------------------------------


async def test_grants_survived_the_rename(upgraded_engine: AsyncEngine) -> None:
    """The whole reason `services` was renamed rather than recreated.

    Checked by execution against `information_schema`, not by reading the
    migration: a GRANT the migration *says* it carries over and a GRANT
    the database actually holds are different claims, and only the second
    keeps least privilege real.
    """
    async with upgraded_engine.connect() as conn:
        grants = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT grantee, table_name, privilege_type "
                        "FROM information_schema.role_table_grants "
                        "WHERE table_name IN ('components', 'connections') "
                        "AND grantee NOT IN ('PUBLIC', current_user)"
                    )
                )
            ).all()
        )

    # Carried across the rename, unchanged.
    assert ("correlation-engine", "components", "SELECT") in grants
    assert ("api-reader", "components", "SELECT") in grants
    assert ("registry-admin", "components", "DELETE") in grants
    # Re-granted explicitly by this migration, matching what each role
    # held on service_dependencies. `mcp-reader` is in this list because
    # it is the one that was missed on the first pass — beab08d5f92f
    # granted it SELECT on service_dependencies, and dropping that table
    # without re-granting silently took a read away from the MCP tools.
    # A rename must not quietly shrink a role any more than it may
    # quietly widen one.
    assert ("correlation-engine", "connections", "SELECT") in grants
    assert ("api-reader", "connections", "SELECT") in grants
    assert ("mcp-reader", "connections", "SELECT") in grants
    assert ("mcp-reader", "components", "SELECT") in grants
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert ("registry-admin", "connections", verb) in grants


async def test_the_grant_set_is_exactly_what_was_carried_across(
    upgraded_engine: AsyncEngine,
) -> None:
    """Set equality, not `in`.

    The subset assertions above catch a grant that was *lost* — which is
    the mistake actually made while writing this migration (mcp-reader's
    SELECT was initially not carried over). They cannot catch a grant
    that was *gained*, which is the mistake `.claude/rules/database.md`
    cares about more: a rename must not become a quiet widening. So this
    pins the whole set.

    If a later phase legitimately grants something new on these tables,
    this test failing is the intended prompt to justify it, not noise to
    delete.
    """
    async with upgraded_engine.connect() as conn:
        grants = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT grantee, table_name, privilege_type "
                        "FROM information_schema.role_table_grants "
                        "WHERE table_name IN ('components', 'connections', 'contracts') "
                        "AND grantee NOT IN ('PUBLIC', current_user)"
                    )
                )
            ).all()
        )

    expected = {
        # Carried by the rename from `services`.
        ("correlation-engine", "components", "SELECT"),
        ("api-reader", "components", "SELECT"),
        ("anomaly-detector", "components", "SELECT"),
        ("ingest-gateway", "components", "SELECT"),
        ("mcp-reader", "components", "SELECT"),
        # Re-granted explicitly, matching what each role held on
        # `service_dependencies`.
        ("correlation-engine", "connections", "SELECT"),
        ("api-reader", "connections", "SELECT"),
        ("mcp-reader", "connections", "SELECT"),
    } | {
        ("registry-admin", table, verb)
        for table in ("components", "connections")
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }
    # `contracts` appears in neither set: field 17, no grants at all.
    assert grants == expected


async def test_no_reader_role_gained_a_write(upgraded_engine: AsyncEngine) -> None:
    """`.claude/rules/database.md`: add a role, never widen one. If
    correlation-engine or api-reader can write a connection, this
    migration widened a role instead of carrying one across."""
    async with upgraded_engine.connect() as conn:
        writes = set(
            (
                await conn.execute(
                    sa.text(
                        "SELECT grantee, table_name, privilege_type "
                        "FROM information_schema.role_table_grants "
                        "WHERE table_name IN ('components', 'connections', 'contracts') "
                        "AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE') "
                        "AND grantee NOT IN ('PUBLIC', current_user)"
                    )
                )
            ).all()
        )
    offenders = {
        row
        for row in writes
        if row[0] in {"correlation-engine", "api-reader", "mcp-reader"}
    }
    assert offenders == set()


# --- field 17: no contract content this phase -------------------------


async def test_contracts_exists_and_no_role_can_touch_it(upgraded_engine: AsyncEngine) -> None:
    """Created for Phase 28 and, exactly as Phase 26 did for the fact
    tables, granted to nobody — there is no component with a need yet."""
    assert await _scalar(upgraded_engine, "SELECT count(*) FROM contracts") == 0
    grants = await _scalar(
        upgraded_engine,
        "SELECT count(*) FROM information_schema.role_table_grants "
        "WHERE table_name = 'contracts' AND grantee NOT IN ('PUBLIC', current_user)",
    )
    assert grants == 0


async def test_every_migrated_connection_has_a_null_contract(
    upgraded_engine: AsyncEngine,
) -> None:
    non_null = await _scalar(
        upgraded_engine, "SELECT count(*) FROM connections WHERE contract_id IS NOT NULL"
    )
    assert non_null == 0


# --- constraints the database enforces itself -------------------------


async def test_two_kinds_between_the_same_pair_are_allowed(
    upgraded_engine: AsyncEngine,
) -> None:
    """The composite unique is `(from, to, kind)` — the reason this could
    not be a rename of `service_dependencies`, whose PK was the untyped
    pair. A second `sql` edge on the same pair is still rejected."""
    insert = (
        "INSERT INTO connections (from_component_id, to_component_id, kind) "
        "SELECT f.id, t.id, 'sql' FROM components f, components t "
        "WHERE f.name = 'order-service' AND t.name = 'inventory-service'"
    )
    async with upgraded_engine.begin() as conn:
        await conn.execute(sa.text(insert))

    with pytest.raises(IntegrityError):
        async with upgraded_engine.begin() as conn:
            await conn.execute(sa.text(insert))

    # Leave the table as it was found, so test ordering in this module
    # cannot change what a later test sees.
    async with upgraded_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM connections WHERE kind = 'sql'"))


async def test_a_self_connection_is_rejected_by_the_database(
    upgraded_engine: AsyncEngine,
) -> None:
    with pytest.raises(IntegrityError):
        async with upgraded_engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO connections (from_component_id, to_component_id, kind) "
                    "SELECT c.id, c.id, 'http' FROM components c WHERE c.name = 'order-service'"
                )
            )


async def test_an_unknown_connection_kind_is_rejected_by_the_database(
    upgraded_engine: AsyncEngine,
) -> None:
    """`ConnectionKind` is a closed set because it selects a probe in
    Phase 31. The database enforces that, not only the pydantic layer."""
    with pytest.raises(IntegrityError):
        async with upgraded_engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO connections (from_component_id, to_component_id, kind) "
                    "SELECT f.id, t.id, 'carrier-pigeon' FROM components f, components t "
                    "WHERE f.name = 'order-service' AND t.name = 'payments-service'"
                )
            )


async def test_an_unknown_component_kind_is_rejected_by_the_database(
    upgraded_engine: AsyncEngine,
) -> None:
    with pytest.raises(IntegrityError):
        async with upgraded_engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE components SET kind = 'microfrontend' WHERE name = 'order-service'")
            )
