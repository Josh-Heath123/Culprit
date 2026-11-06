"""Who is calling: a signed agent, or the project token (Phase 33 part 2).

`require_agent` is the whole of an agent's authentication. It rebuilds the
canonical request from what this process actually received — the method and
path of the route being handled, the bytes of the body — and asks
`signing.decide` whether the stated agent's key signed exactly that, recently,
with a nonce never used before. The key is read on every request, so a
revoked agent is refused on its very next one. The nonce is recorded only
once everything else has passed, so a request that fails never consumes one.

A refusal is one 401 with one message. Which check failed — no such agent,
revoked, stale, replayed, a bad signature — is logged here, and not told to
the caller: a forger learns nothing from the answer.
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import signing, tables
from app.facts import dependencies as facts_dependencies

logger = structlog.get_logger("agents.auth")

REFUSED = "request refused"

#: How long a nonce is kept: past the last moment any request that used it
#: could still be fresh (see authenticate_agent), and a minute more.
NONCE_RETENTION_SECONDS = 2 * signing.MAX_SKEW_SECONDS + 60


@dataclass(frozen=True)
class AgentPrincipal:
    id: str


@dataclass(frozen=True)
class Submitter:
    """Who stored something: an agent, or whoever holds the project token."""

    agent: AgentPrincipal | None

    @property
    def label(self) -> str:
        return f"agent:{self.agent.id}" if self.agent else "project-token"


def _session(state_name: str):
    async def dependency(request: Request) -> AsyncIterator[AsyncSession]:
        factory: async_sessionmaker[AsyncSession] = getattr(request.app.state, state_name)
        async with factory() as session:
            yield session

    return dependency


get_admin_session = _session("agent_admin_session_factory")
get_registrar_session = _session("agent_registrar_session_factory")
get_gateway_session = _session("agent_gateway_session_factory")


def _refuse(reason: str, agent_id: str | None = None) -> HTTPException:
    logger.warning("agent_request_refused", reason=reason, agent=agent_id)
    return HTTPException(status_code=401, detail=REFUSED)


def _signed_path(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    return path


async def authenticate_agent(request: Request, session: AsyncSession) -> AgentPrincipal:
    headers = request.headers
    agent_id = headers.get(signing.HEADER_AGENT)
    timestamp = headers.get(signing.HEADER_TIMESTAMP)
    nonce = headers.get(signing.HEADER_NONCE)
    signature = headers.get(signing.HEADER_SIGNATURE)
    if not (agent_id and timestamp and nonce and signature):
        raise _refuse("missing signature headers")
    if not signing.AGENT_ID.match(agent_id):
        raise _refuse("malformed agent id")
    try:
        stamped = int(timestamp)
    except ValueError:
        raise _refuse("malformed timestamp", agent_id) from None

    signed = signing.SignedRequest(
        method=request.method,
        path=_signed_path(request),
        body=await request.body(),
        timestamp=stamped,
        nonce=nonce,
        agent_id=agent_id,
    )
    row = (
        await session.execute(
            select(tables.agents.c.public_key, tables.agents.c.revoked_at).where(
                tables.agents.c.id == agent_id
            )
        )
    ).first()
    key = signing.AgentKey(bytes(row.public_key), row.revoked_at is not None) if row else None
    now = int(time.time())
    # Everything but the nonce, first: a request that fails here must not
    # spend one.
    if not signing.decide(key, signed, signature, now, lambda _nonce: False):
        raise _refuse(
            "unknown agent" if key is None else "revoked" if key.revoked else "invalid or stale",
            agent_id,
        )

    # The nonce, atomically: the insert succeeds once per (agent, nonce).
    recorded = (
        await session.execute(
            pg_insert(tables.agent_nonces)
            .values(agent_id=agent_id, nonce=nonce, seen_at=sa_now())
            .on_conflict_do_nothing()
            .returning(tables.agent_nonces.c.nonce)
        )
    ).first()
    # A request can be fresh until MAX_SKEW past its timestamp, and its
    # timestamp up to MAX_SKEW past the moment it arrived: so a nonce can
    # matter until 2 * MAX_SKEW after `seen_at`. Kept a minute beyond that,
    # for clocks a little apart between replicas.
    await session.execute(
        delete(tables.agent_nonces).where(
            tables.agent_nonces.c.seen_at < sa_now(offset_seconds=-NONCE_RETENTION_SECONDS)
        )
    )
    await session.commit()
    if recorded is None:
        raise _refuse("replayed nonce", agent_id)
    return AgentPrincipal(id=agent_id)


def sa_now(offset_seconds: int = 0):
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


async def require_agent(
    request: Request, session: AsyncSession = Depends(get_gateway_session)
) -> AgentPrincipal:
    return await authenticate_agent(request, session)


async def require_project_token_or_agent(
    request: Request, authorization: str | None = Header(default=None)
) -> Submitter:
    """`POST /investigations`: CI posts what `culprit diagnose` writes with
    the project token; an agent posts its own walk, signed. Either way the
    caller is recorded (`investigations.submitted_by`). The gateway's
    session is opened only for a signed request: a project-token caller
    never touches the agent tables."""
    if request.headers.get(signing.HEADER_SIGNATURE) is not None:
        factory: async_sessionmaker[AsyncSession] = request.app.state.agent_gateway_session_factory
        async with factory() as session:
            return Submitter(agent=await authenticate_agent(request, session))
    await facts_dependencies.require_project_token(authorization)
    return Submitter(agent=None)
