"""API key authentication for ingest-gateway.

Phase 14: keys are now issued through the service registry
(api/app/registry/), so the in-memory map this module loads at startup
can go stale the moment an admin issues, revokes, or disables a key
through that API while this process is already running. The fix isn't
"query the DB every request" (that's the throughput cliff for a
telemetry-ingestion hot path) — it's: keep serving the in-memory map,
and go back to the DB at most once per _MIN_RELOAD_INTERVAL_S, so a
flood of requests (valid or not) can't turn into a flood of DB round
trips.

Phase 26 (docs/DIAGNOSTIC_PLAN.md) corrected *when* that reload happens.
It used to fire only on a lookup miss, which sounds like a cheaper
version of the same thing and is not: a revoked key still hashes to an
entry in the stale map, so it always hits, so it never triggers the
reload that would have removed it. Revocation silently did nothing until
some unrelated request presented an unknown key. See
`ApiKeyStore.authenticate`.
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

#: How often ApiKeyStore is willing to go back to the DB and reload
#: before an authentication lookup. Bounds worst-case DB load from any
#: request flood, valid or malicious, to one reload per this many
#: seconds. It is also the worst-case window in which a revoked key
#: still authenticates — stated as such in docs/LIMITS.md rather than
#: left to be discovered.
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
    """Loads active key hashes once at startup, then refreshes them at
    most once per _MIN_RELOAD_INTERVAL_S on the authentication path (see
    module docstring for why that isn't reload-on-miss any more)."""

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
        """Refreshes the map at most once per _MIN_RELOAD_INTERVAL_S, and
        never propagates a database failure onto the ingest path.

        Both halves matter. `load()` stamps `_last_reload_at` only on
        success, so a failing database would otherwise leave the
        timestamp stale and make *every* subsequent request due for a
        reload — each one paying a full connection timeout, serialised
        behind `_reload_lock`. A Postgres blip would become total ingest
        unavailability, and would do so only because of the reload this
        method exists to perform: under the old reload-on-miss code, a
        holder of a valid key kept authenticating from the in-memory map
        while the database was down, and telemetry kept landing in Redis.

        So the interval is enforced on the *attempt*, and a failure is
        logged and swallowed. The cost is serving a map up to one more
        interval stale — bounded, and already stated in docs/LIMITS.md.
        The alternative is failing requests that would otherwise succeed.
        """
        if time.monotonic() - self._last_reload_at < _MIN_RELOAD_INTERVAL_S:
            return
        async with self._reload_lock:
            # Re-check inside the lock: another request may have already
            # reloaded while this one was waiting for it.
            if time.monotonic() - self._last_reload_at < _MIN_RELOAD_INTERVAL_S:
                return
            self._last_reload_at = time.monotonic()
            try:
                await self.load()
            except Exception:
                logger.warning("api_key_reload_failed", exc_info=True)

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
        # Refresh *before* the lookup, not only after a miss.
        #
        # Phase 26 (docs/DIAGNOSTIC_PLAN.md) fixed a real security bug
        # here: reloading only on a miss means a revoked key is never
        # re-checked, because a revoked key still hashes to an entry in
        # the stale map and therefore always *hits*. Revocation only took
        # effect if some unrelated request happened to present an unknown
        # key first — which, for an attacker holding a key that was just
        # revoked, is never. The whole point of revoking a credential is
        # that it stops working.
        #
        # This costs at most one reload per _MIN_RELOAD_INTERVAL_S
        # regardless of request rate (the same bound the miss path
        # already had), so the throughput reasoning in this module's
        # docstring still holds: six queries a minute, not one per
        # request. It also subsumes the old miss-triggered reload — a
        # newly-issued key is now picked up by the same call, so there is
        # no second lookup below.
        await self._reload_if_due()
        entry = self._match(_hash_key(presented_key))
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


#: How much of a rejected key gets logged — enough to correlate a
#: specific rejected request with a specific key/service while looking
#: it up in the registry, never enough to be usable as a credential
#: itself (see docs/SELF_HOSTED_PLAN.md Phase 15's hardening steps).
_LOGGED_KEY_PREFIX_LENGTH = 12


async def authenticated_service_name(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("ingest_auth_rejected", reason="missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    presented_key = authorization.removeprefix("Bearer ").strip()
    service_name = await api_key_store.authenticate(presented_key)
    if service_name is None:
        logger.warning(
            "ingest_auth_rejected",
            reason="invalid API key",
            key_prefix=presented_key[:_LOGGED_KEY_PREFIX_LENGTH],
        )
        raise HTTPException(status_code=401, detail="invalid API key")
    return service_name
