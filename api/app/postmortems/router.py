"""Postmortem write path (Phase 18) — mounted at /postmortems in
api/app/main.py, gated by the same require_auth dependency
app/incidents/router.py uses. Unlike the registry/users routers, this is
not admin-only — any authenticated team member may read and write
postmortems.

Reads use the api-reader engine already in app.state (read-only, same
one app/incidents/router.py uses — api-reader already has SELECT on
postmortems, see api/migrations/versions/cc323b6c7779_create_db_roles.py);
writes use a third engine, under postmortem-writer — see app/main.py's
lifespan and app/postmortems/config.py.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from app.auth.dependencies import require_auth
from app.auth.security import AuthenticatedUser
from app.postmortems.schemas import (
    PaginatedPostmortems,
    PostmortemCreate,
    PostmortemOut,
    PostmortemPatch,
)
from app.postmortems.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    UnknownIncident,
    create_postmortem,
    delete_postmortem,
    get_postmortem,
    list_postmortems,
    patch_postmortem,
)

router = APIRouter(prefix="/postmortems", tags=["postmortems"])


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_write_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.postmortem_session_factory
    )
    async with session_factory() as session:
        yield session


def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool


@router.get("", response_model=PaginatedPostmortems)
async def list_postmortems_endpoint(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_read_session),
) -> PaginatedPostmortems:
    items, total = await list_postmortems(session, limit, offset)
    return PaginatedPostmortems(items=items, limit=limit, offset=offset, total=total)


@router.post("", response_model=PostmortemOut, status_code=201)
async def create_postmortem_endpoint(
    body: PostmortemCreate,
    session: AsyncSession = Depends(get_write_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    user: AuthenticatedUser = Depends(require_auth),
) -> PostmortemOut:
    """The API never calls Voyage itself (CLAUDE.md: LLM/embedding calls
    stay server-side in the worker, never blocking this process on a
    rate-limited third-party call) — this only enqueues, exactly like
    POST /incidents/{id}/regenerate-root-cause does for Phase 6's job."""
    try:
        postmortem = await create_postmortem(session, body, author_user_id=user.id)
    except UnknownIncident as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await arq_pool.enqueue_job("embed_postmortem", str(postmortem.id))
    return postmortem


@router.get("/{postmortem_id}", response_model=PostmortemOut)
async def get_postmortem_endpoint(
    postmortem_id: UUID, session: AsyncSession = Depends(get_read_session)
) -> PostmortemOut:
    postmortem = await get_postmortem(session, postmortem_id)
    if postmortem is None:
        raise HTTPException(status_code=404, detail="postmortem not found")
    return postmortem


@router.patch("/{postmortem_id}", response_model=PostmortemOut)
async def patch_postmortem_endpoint(
    postmortem_id: UUID,
    body: PostmortemPatch,
    session: AsyncSession = Depends(get_write_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> PostmortemOut:
    """An empty body (`{}`) is a valid request — see
    app/postmortems/service.py::patch_postmortem's docstring for why
    that's also how a UI "retry" action re-enqueues a failed embed
    without changing any content."""
    result = await patch_postmortem(session, postmortem_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="postmortem not found")
    postmortem, should_reembed = result
    if should_reembed:
        await arq_pool.enqueue_job("embed_postmortem", str(postmortem.id))
    return postmortem


@router.delete("/{postmortem_id}", status_code=204)
async def delete_postmortem_endpoint(
    postmortem_id: UUID, session: AsyncSession = Depends(get_write_session)
) -> Response:
    deleted = await delete_postmortem(session, postmortem_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="postmortem not found")
    return Response(status_code=204)
