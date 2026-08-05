"""Phase 15: oversized/gzip-bomb payloads must be rejected before they
ever reach otlp_decode.py's protobuf parsing, and the ingest rate
limiter must bucket by authenticated service, not client IP — every
service behind one NAT would otherwise share one bucket and throttle
each other. See docs/SELF_HOSTED_PLAN.md's Phase 15 hardening steps and
Known Trap 4.
"""

import gzip
import uuid
from datetime import UTC, datetime

import app.ingest_gateway.main as main_module
import pytest
import pytest_asyncio
from app.ingest_gateway.limiter import _rate_limit_key
from app.ingest_gateway.main import _maybe_decompress
from app.registry.keys import generate_api_key, hash_api_key
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from starlette.requests import Request


def _make_gzip_payload(decompressed_size: int) -> bytes:
    """A small compressed payload that decompresses to `decompressed_size`
    bytes of a single repeated byte — gzip compresses long runs of the
    same byte extremely well, so this stays tiny on the wire regardless
    of how large decompressed_size is, the same shape a real gzip bomb
    would have."""
    return gzip.compress(b"\x00" * decompressed_size)


def test_uncompressed_body_within_limit_passes_through() -> None:
    body = b"x" * 100
    assert _maybe_decompress(body, None) == body


def test_uncompressed_body_over_limit_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "INGEST_MAX_BODY_BYTES", 10)
    with pytest.raises(HTTPException) as exc_info:
        _maybe_decompress(b"x" * 11, None)
    assert exc_info.value.status_code == 413


def test_gzip_payload_within_limit_decompresses() -> None:
    payload = _make_gzip_payload(100)
    assert len(_maybe_decompress(payload, "gzip")) == 100


def test_gzip_bomb_rejected_without_fully_materializing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "INGEST_MAX_BODY_BYTES", 1024)
    # Compresses to a few KB but would decompress to 500MB -- if this
    # regresses back to gzip.decompress()'s unbounded behavior, this test
    # is slow/memory-hungry instead of instant, which is itself the
    # signal something's wrong even before the assertion below.
    bomb = _make_gzip_payload(500 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc_info:
        _maybe_decompress(bomb, "gzip")
    assert exc_info.value.status_code == 413


def test_invalid_gzip_payload_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _maybe_decompress(b"not actually gzip", "gzip")
    assert exc_info.value.status_code == 400


# ---- rate-limit key: bucketed by authenticated service, not IP ----


def _request_with_auth(header_value: str | None) -> Request:
    headers = [(b"authorization", header_value.encode())] if header_value else []
    scope = {"type": "http", "headers": headers, "client": ("203.0.113.5", 12345)}
    return Request(scope)


@pytest_asyncio.fixture
async def store(
    migrated_database_url: str,  # ordering dependency, see conftest — unused otherwise
    role_database_url,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
):
    """Same monkeypatch-the-already-imported-module approach as
    test_ingest_gateway_key_refresh.py — see that file's module
    docstring for why."""
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


async def _insert_service_and_key(db_engine: AsyncEngine, *, name: str) -> str:
    plaintext = generate_api_key()
    service_id = uuid.uuid4()
    async with db_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO services (id, name, disabled_at) VALUES (:id, :name, NULL)"),
            {"id": service_id, "name": name},
        )
        await conn.execute(
            text(
                "INSERT INTO api_keys (service_id, service_name, key_hash, revoked_at, created_at) "
                "VALUES (:service_id, :service_name, :key_hash, NULL, :created_at)"
            ),
            {
                "service_id": service_id,
                "service_name": name,
                "key_hash": hash_api_key(plaintext),
                "created_at": datetime.now(UTC),
            },
        )
    return plaintext


async def test_two_services_get_independent_rate_limit_keys(
    store, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_a = await _insert_service_and_key(db_engine, name="checkout-api")
    key_b = await _insert_service_and_key(db_engine, name="billing-api")
    await store.load()

    import app.ingest_gateway.limiter as limiter_module

    monkeypatch.setattr(limiter_module, "api_key_store", store)

    # Same client IP for both (203.0.113.5, see _request_with_auth) —
    # the whole point is that the key differs by service, not by the
    # network origin they happen to share.
    key_for_a = _rate_limit_key(_request_with_auth(f"Bearer {key_a}"))
    key_for_b = _rate_limit_key(_request_with_auth(f"Bearer {key_b}"))

    assert key_for_a == "service:checkout-api"
    assert key_for_b == "service:billing-api"
    assert key_for_a != key_for_b


async def test_unauthenticated_request_falls_back_to_ip(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.ingest_gateway.limiter as limiter_module

    monkeypatch.setattr(limiter_module, "api_key_store", store)

    assert _rate_limit_key(_request_with_auth(None)) == "ip:203.0.113.5"
    assert _rate_limit_key(_request_with_auth("Bearer clp_live_not-a-real-key")) == (
        "ip:203.0.113.5"
    )
