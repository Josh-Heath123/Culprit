"""Phase 14: api/app/ingest_gateway/auth.py's ApiKeyStore stopped being a
load-once-at-startup cache and became reactively self-refreshing (see
that module's own docstring) — a key created after the process booted,
a revoked key, or a newly-disabled service's key all need to actually
take effect without restarting the gateway. These are exactly the
failure modes a pure unit test (mocking the DB) can't catch, since the
whole point under test is real DB round trips through the real reload
path (see docs/SELF_HOSTED_PLAN.md's Phase 14, step 5 — "the single most
likely 'the admin API works but ingest still 401s' bug in this phase").

This monkeypatches app.ingest_gateway.auth's module-level
`_session_factory` directly rather than setting INGEST_GATEWAY_DATABASE_URL
and relying on import order: that module creates its DB engine once, at
import time, and by the time this file's fixtures run, some other test
module may already have triggered that import (transitively, via
app.registry.keys — see test_registry_api.py's own module docstring)
against a different database. Monkeypatching the already-imported
module's global is immune to import order — ApiKeyStore.load() and
_update_last_used_at() both look up `_session_factory` by name at call
time, not at def time, so this redirects them correctly no matter when
or how the module was first imported.
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from app.registry.keys import generate_api_key, hash_api_key
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def store(
    migrated_database_url: str,  # ordering dependency, see conftest — unused otherwise
    role_database_url,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
):
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE services, service_dependencies, api_keys CASCADE"))

    import app.ingest_gateway.auth as auth_module

    ingest_url = role_database_url("ingest-gateway", "INGEST_GATEWAY_DB_PASSWORD")
    test_engine = create_async_engine(ingest_url)
    monkeypatch.setattr(
        auth_module, "_session_factory", async_sessionmaker(test_engine, expire_on_commit=False)
    )

    yield auth_module.ApiKeyStore()

    await test_engine.dispose()


async def _insert_service_and_key(
    db_engine: AsyncEngine, *, name: str, disabled: bool = False, revoked: bool = False
) -> str:
    """Inserted directly via the superuser engine, not through the
    registry API — this file tests ApiKeyStore in isolation from it (see
    test_registry_api.py for the HTTP-level registry tests). Returns the
    plaintext key."""
    plaintext = generate_api_key()
    service_id = uuid.uuid4()
    disabled_at = datetime.now(UTC) if disabled else None
    async with db_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO services (id, name, disabled_at) VALUES (:id, :name, :disabled_at)"),
            {"id": service_id, "name": name, "disabled_at": disabled_at},
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys (service_id, service_name, key_hash, revoked_at) "
                "VALUES (:service_id, :service_name, :key_hash, :revoked_at)"
            ),
            {
                "service_id": service_id,
                "service_name": name,
                "key_hash": hash_api_key(plaintext),
                "revoked_at": datetime.now(UTC) if revoked else None,
            },
        )
    return plaintext


async def _revoke(db_engine: AsyncEngine, plaintext: str) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE api_keys SET revoked_at = now() WHERE key_hash = :key_hash"),
            {"key_hash": hash_api_key(plaintext)},
        )


async def _disable_service(db_engine: AsyncEngine, name: str) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE services SET disabled_at = now() WHERE name = :name"), {"name": name}
        )


def _force_reload_due(store) -> None:
    """White-box: bypasses the real 10s _MIN_RELOAD_INTERVAL_S wait so
    the test doesn't have to sleep for it — everything else about the
    reload path (the DB query, the filter on revoked_at/disabled_at, the
    in-memory map swap) runs for real."""
    store._last_reload_at = 0.0


async def test_key_created_before_load_authenticates_immediately(
    store, db_engine: AsyncEngine
) -> None:
    plaintext = await _insert_service_and_key(db_engine, name="checkout-api")
    await store.load()
    assert await store.authenticate(plaintext) == "checkout-api"


async def test_key_created_after_load_authenticates_once_the_reload_interval_elapses(
    store, db_engine: AsyncEngine
) -> None:
    await store.load()  # baseline: nothing in the DB yet

    plaintext = await _insert_service_and_key(db_engine, name="checkout-api")

    # Too soon: load() just ran, so the miss below must NOT trigger a
    # reload yet — this is the rate limit (_MIN_RELOAD_INTERVAL_S) doing
    # its job, not a bug.
    assert await store.authenticate(plaintext) is None

    _force_reload_due(store)
    assert await store.authenticate(plaintext) == "checkout-api"


async def test_revoked_key_stops_authenticating_once_the_reload_interval_elapses(
    store, db_engine: AsyncEngine
) -> None:
    plaintext = await _insert_service_and_key(db_engine, name="checkout-api")
    await store.load()
    assert await store.authenticate(plaintext) == "checkout-api"

    await _revoke(db_engine, plaintext)
    _force_reload_due(store)

    # A revoked key's hash is still a cache HIT until the next reload
    # actually runs -- presenting a never-seen key first is what forces
    # that reload (a miss is the only thing that triggers one; see
    # ApiKeyStore.authenticate()'s own docstring/logic).
    assert await store.authenticate("clp_live_definitely-not-a-real-key") is None
    assert await store.authenticate(plaintext) is None


async def test_disabled_services_key_stops_authenticating_once_the_reload_interval_elapses(
    store, db_engine: AsyncEngine
) -> None:
    plaintext = await _insert_service_and_key(db_engine, name="checkout-api")
    await store.load()
    assert await store.authenticate(plaintext) == "checkout-api"

    await _disable_service(db_engine, "checkout-api")
    _force_reload_due(store)

    assert await store.authenticate("clp_live_definitely-not-a-real-key") is None
    assert await store.authenticate(plaintext) is None


async def test_load_never_returns_a_revoked_or_disabled_key(
    store, db_engine: AsyncEngine
) -> None:
    live = await _insert_service_and_key(db_engine, name="checkout-api")
    await _insert_service_and_key(db_engine, name="billing-api", revoked=True)
    await _insert_service_and_key(db_engine, name="fraud-api", disabled=True)

    await store.load()

    assert await store.authenticate(live) == "checkout-api"
    assert len(store._hash_to_entry) == 1
