"""Per-request auth dependencies (Phase 16 rewrite).

require_auth used to just decode a JWT and return the username inside
it — Phase 9's whole auth model was "the token is valid or it isn't."
Phase 16 adds a live users table with a disabled_at a token can't see,
so require_auth now also does a (cached) DB read to confirm the account
is still active. See _resolve_user's docstring for the caching
rationale (Known Trap 3, docs/SELF_HOSTED_PLAN.md Phase 16).
"""

import time
from uuid import UUID

import jwt
import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.repository import get_user_by_id
from app.auth.security import AuthenticatedUser, decode_access_token

logger = structlog.get_logger("auth")

#: How long a resolved user (role + disabled status) stays cached
#: in-process, keyed by user id, before the next authenticated request
#: for that user re-reads the row. Bounds the DB load a read added to
#: *every* authenticated request to one query per user per this many
#: seconds, not one per request (Known Trap 3) — and is the reason a
#: disabled account's existing token stops working "within its
#: remaining lifetime," not instantly: up to this many seconds can still
#: elapse after disabling someone before their next request is rejected.
_USER_CACHE_TTL_S = 30.0
_user_cache: dict[UUID, tuple[AuthenticatedUser, float]] = {}


async def _resolve_user(request: Request, uid: UUID) -> AuthenticatedUser | None:
    cached = _user_cache.get(uid)
    if cached is not None:
        user, cached_at = cached
        if time.monotonic() - cached_at < _USER_CACHE_TTL_S:
            return user

    # api-reader, not auth-service: this path only ever reads (see
    # api/migrations/versions/fbf4cb16570a_create_users_table.py's grant
    # of SELECT on users to api-reader specifically for this) — the
    # write-capable auth-service engine is app/auth/router.py's alone.
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        row = await get_user_by_id(session, uid)

    if row is None or row.disabled_at is not None:
        _user_cache.pop(uid, None)
        return None

    user = AuthenticatedUser(id=row.id, username=row.username, role=row.role)
    _user_cache[uid] = (user, time.monotonic())
    return user


async def require_auth(
    request: Request, authorization: str | None = Header(default=None)
) -> AuthenticatedUser:
    """FastAPI dependency protecting the incidents/registry/users routers
    (see app/main.py — applied at include_router(..., dependencies=[...])
    level). Returns the authenticated user on success; every failure
    path logs the specific reason (Phase 10: no silent 401s) before
    raising, while the HTTP response itself stays generic.

    Handlers that need the resolved user must declare their own
    `user: AuthenticatedUser = Depends(require_auth)` parameter — a
    router-level dependency's return value isn't otherwise visible to
    the handler. FastAPI caches the dependency call per request, so
    declaring it again here costs nothing extra.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        logger.warning("auth_request_rejected", reason="missing bearer token")
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        logger.warning("auth_request_rejected", reason="token expired")
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("auth_request_rejected", reason="invalid token")
        raise HTTPException(status_code=401, detail="invalid token") from exc

    user = await _resolve_user(request, payload.uid)
    if user is None:
        logger.warning(
            "auth_request_rejected", reason="account disabled or deleted", uid=str(payload.uid)
        )
        raise HTTPException(status_code=401, detail="account disabled")
    return user


async def require_admin(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user
