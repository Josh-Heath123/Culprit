"""API key authentication for ingest-gateway.

Three fixed, manually-provisioned keys (one per demo service) — no
onboarding flow. The service_name a request is attributed to always comes
from here, never from the OTLP payload itself: that's the actual
multi-tenant boundary, not just "requires a header."
"""

import hashlib
import secrets

from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ApiKey
from app.ingest_gateway.config import INGEST_GATEWAY_DATABASE_URL

_engine = create_async_engine(INGEST_GATEWAY_DATABASE_URL)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


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
    """Loads the small, fixed set of provisioned key hashes once — three
    manually-provisioned keys don't need a DB round trip per request."""

    def __init__(self) -> None:
        self._hash_to_service: dict[str, str] = {}

    async def load(self) -> None:
        async with _session_factory() as session:
            result = await session.execute(select(ApiKey.key_hash, ApiKey.service_name))
            self._hash_to_service = {row.key_hash: row.service_name for row in result}

    def authenticate(self, presented_key: str) -> str | None:
        presented_hash = _hash_key(presented_key)
        for stored_hash, service_name in self._hash_to_service.items():
            if secrets.compare_digest(presented_hash, stored_hash):
                return service_name
        return None


api_key_store = ApiKeyStore()


async def authenticated_service_name(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    presented_key = authorization.removeprefix("Bearer ").strip()
    service_name = api_key_store.authenticate(presented_key)
    if service_name is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    return service_name
