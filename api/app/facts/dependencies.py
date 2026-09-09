"""Project-token auth for `POST /facts/captures`.

Phase 28 field 9: "Authenticated with a project token, not a user JWT."

The reason it is not a user JWT is worth stating rather than inferring.
The caller is `culprit intent | culprit push` in somebody's CI job. It
has no browser, no login, and no session to refresh; issuing it a user
JWT would mean either a long-lived user token in CI secrets (worse than
a scoped project token, because a user token can do everything a user
can) or an interactive login step in a non-interactive place.

So it is a single shared bearer credential, compared in constant time,
with exactly one thing it can do: post a capture bundle. It cannot read
incidents, cannot touch the registry and cannot log in — the DB role
behind it (`fact-writer`) has INSERT on two tables and SELECT on one.

**Unset means refuse, not allow.** An empty `CULPRIT_PROJECT_TOKEN`
would otherwise compare equal to an empty presented token, which is the
same fail-open shape `app/env.py` exists to stamp out. The empty case is
guarded explicitly rather than left to fall out of `compare_digest`'s
behaviour on two empty strings — the same guard, and the same reasoning,
as `require_auth_or_agent`'s handling of `AGENT_AUTOMATION_TOKEN`.
"""

import hmac
import os
from collections.abc import AsyncIterator

import structlog
from fastapi import Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("facts.auth")

#: Read with a blank default rather than `require_env`, matching
#: AGENT_AUTOMATION_TOKEN: an install that never uploads captures (every
#: install today — `culprit intent` prints to stdout and does not push,
#: Phase 28 field 17) should not fail to boot over a credential it will
#: not use. Blank makes the endpoint refuse every request; it does not
#: make it open.
CULPRIT_PROJECT_TOKEN = os.environ.get("CULPRIT_PROJECT_TOKEN", "")


async def require_project_token(authorization: str | None = Header(default=None)) -> None:
    if not CULPRIT_PROJECT_TOKEN:
        logger.warning("capture_rejected", reason="CULPRIT_PROJECT_TOKEN is not configured")
        raise HTTPException(status_code=401, detail="capture upload is not configured")
    if authorization is None or not authorization.startswith("Bearer "):
        logger.warning("capture_rejected", reason="missing bearer token")
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(presented, CULPRIT_PROJECT_TOKEN):
        logger.warning("capture_rejected", reason="invalid project token")
        raise HTTPException(status_code=401, detail="invalid project token")


async def get_fact_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.fact_session_factory
    async with session_factory() as session:
        yield session
