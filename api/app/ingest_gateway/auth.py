"""API key authentication for ingest-gateway.

Phase 14: keys are now issued through the service registry
(api/app/registry/), so the in-memory map this module loads at startup
can go stale the moment an admin issues, revokes, or disables a key
through that API while this process is already running. The fix isn't
"query the DB every request" (that's the throughput cliff for a
telemetry-ingestion hot path) — it's: keep serving the in-memory map for
the common case, and only go back to the DB when a *miss* suggests the
map might be stale, rate-limited so a flood of bad keys can't turn into
a flood of DB round trips.
"""

import asyncio
import hashlib
import secrets
import time
from uuid import UUID

import structlog
from fastapi import Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql import func

from app.db.models import ApiKey, Service
from app.ingest_gateway.config import INGEST_GATEWAY_DATABASE_URL

logger = structlog.get_logger("ingest_gateway.auth")

_engine = create_async_engine(INGEST_GATEWAY_DATABASE_URL)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)

#: On an auth *miss*, how often ApiKeyStore is willing to go back to the
#: DB and reload before trying the lookup again. Bounds worst-case DB
#: load from a flood of invalid/malicious keys to one reload per this
#: many seconds, not one per request.
_MIN_RELOAD_INTERVAL_S = 10.0

#: How often, per key, a successful auth is allowed to trigger a
#: last_used_at write. This is metadata for the registry UI, not
#: anything correctness-sensitive — one write a minute per active key is
#: plenty, and the alternative (once per request) is real write
#: amplification on a hot ingest path for no benefit.
_LAST_USED_UPDATE_INTERVAL_S = 60.0


def _hash_key(plaintext: str) -> str:
    # Plain SHA-256, not a slow/salted KDF (argon2, bcrypt) — deliberate,
    # not an oversight: these are high-entropy generated tokens (see
    # infra/.env.prod.example), not user-chosen passwords, so there's no
    # low-entropy-guessing risk a slow hash would defend against. Compared
    # via secrets.compare_digest below, not ==, so this doesn't leak
    # timing info either. OPERATOR_PASSWORD_HASH (app/auth/), which *is*
    # a real password, uses argon2 — see that module.
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class ApiKeyStore:
    """Loads active key hashes once at startup, then keeps them fresh
    reactively (see module docstring) rather than on a fixed timer —
    there's no reason to reload every N seconds if nothing's actually
    missing lookups."""

    def __init__(self) -> None:
        self._hash_to_entry: dict[str, tuple[str, UUID]] = {}
        self._last_reload_at: float = 0.0
        self._last_used_update_at: dict[UUID, float] = {}
        self._reload_lock = asyncio.Lock()
        #: Keeps the fire-and-forget last_used_at update tasks referenced
        #: until they finish — an unreferenced asyncio.Task can be
        #: garbage-collected mid-execution, silently dropping the write.
        self._background_tasks: set[asyncio.Task] = set()

    async def load(self) -> None:
        async with _session_factory() as session:
            rows = (
                await session.execute(
                    select(ApiKey.key_hash, ApiKey.service_name, ApiKey.id)
                    .join(Service, Service.id == ApiKey.service_id)
                    .where(ApiKey.revoked_at.is_(None), Service.disabled_at.is_(None))
                )
            ).all()
        self._hash_to_entry = {row.key_hash: (row.service_name, row.id) for row in rows}
        self._last_reload_at = time.monotonic()

    async def _reload_if_due(self) -> None:
        if time.monotonic() - self._last_reload_at < _MIN_RELOAD_INTERVAL_S:
            return
        async with self._reload_lock:
            # Re-check inside the lock: another request may have already
            # reloaded while this one was waiting for it.
            if time.monotonic() - self._last_reload_at < _MIN_RELOAD_INTERVAL_S:
                return
            await self.load()

    def _schedule_last_used_update(self, key_id: UUID) -> None:
        now = time.monotonic()
        last = self._last_used_update_at.get(key_id, 0.0)
        if now - last < _LAST_USED_UPDATE_INTERVAL_S:
            return
        self._last_used_update_at[key_id] = now
        # Fire-and-forget: the caller (authenticate(), on the ingest
        # request's critical path) must not wait on this write.
        task = asyncio.create_task(_update_last_used_at(key_id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def authenticate(self, presented_key: str) -> str | None:
        presented_hash = _hash_key(presented_key)
        entry = self._match(presented_hash)
        if entry is None:
            await self._reload_if_due()
            entry = self._match(presented_hash)
        if entry is None:
            return None
        service_name, key_id = entry
        self._schedule_last_used_update(key_id)
        return service_name

    def _match(self, presented_hash: str) -> tuple[str, UUID] | None:
        # secrets.compare_digest still runs against every stored hash
        # (not a dict lookup by presented_hash directly), preserving the
        # original constant-time-per-candidate comparison rather than
        # introducing a timing side-channel via early dict-key-miss exit.
        for stored_hash, entry in self._hash_to_entry.items():
            if secrets.compare_digest(presented_hash, stored_hash):
                return entry
        return None


async def _update_last_used_at(key_id: UUID) -> None:
    try:
        async with _session_factory() as session:
            await session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=func.now())
            )
            await session.commit()
    except Exception:
        # Never let a metadata write take down request handling that
        # already succeeded — this task isn't awaited by anything.
        logger.warning("last_used_at_update_failed", key_id=str(key_id), exc_info=True)


api_key_store = ApiKeyStore()


async def authenticated_service_name(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    presented_key = authorization.removeprefix("Bearer ").strip()
    service_name = await api_key_store.authenticate(presented_key)
    if service_name is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return service_name
