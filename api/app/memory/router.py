"""Engineering-memory API (Phase 21, docs/AI_NATIVE_PLAN.md) — mounted at
the repo root in api/app/main.py (no router-level auth dependency, unlike
every other router in this app — see below for why).

Reads use the api-reader engine already in app.state (read-only, same one
app/postmortems/router.py uses — api-reader already has SELECT on both
new tables, see the Phase 21 migration); writes use the same
postmortem-writer engine app/postmortems/router.py uses too (no new
engine — invariant 10, docs/AI_NATIVE_PLAN.md §1).

Every endpoint here gates on `require_auth` individually rather than via
`app.include_router(..., dependencies=[...])` the way every other router
in this app does: `POST /ai-change-records` needs `require_auth_or_agent`
instead, and a router-level dependency runs for *every* route under it
regardless of what the route itself declares — there is no way to make
one route "opt out" of a router-level dependency in FastAPI. Per-route
`Depends()` is the only way to give one endpoint a different auth
requirement than its siblings.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.dependencies import require_auth, require_auth_or_agent
from app.auth.security import AuthenticatedUser
from app.memory.schemas import (
    AiChangeRecordCreate,
    AiChangeRecordDetail,
    AiChangeRecordOut,
    ArchitectureDecisionCreate,
    ArchitectureDecisionOut,
    ArchitectureDecisionPatch,
    InvariantViolationCreate,
    InvariantViolationOut,
    PaginatedAiChangeRecords,
    PaginatedArchitectureDecisions,
)
from app.memory.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    create_ai_change_record,
    create_architecture_decision,
    create_invariant_violation,
    delete_architecture_decision,
    get_ai_change_record_detail,
    get_architecture_decision,
    list_ai_change_records,
    list_architecture_decisions,
    patch_architecture_decision,
)

router = APIRouter(tags=["memory"])


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


# --- Architecture decisions ----------------------------------------------


@router.get(
    "/architecture-decisions",
    response_model=PaginatedArchitectureDecisions,
    dependencies=[Depends(require_auth)],
)
async def list_architecture_decisions_endpoint(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_read_session),
) -> PaginatedArchitectureDecisions:
    items, total = await list_architecture_decisions(session, limit, offset)
    return PaginatedArchitectureDecisions(items=items, limit=limit, offset=offset, total=total)


@router.post(
    "/architecture-decisions",
    response_model=ArchitectureDecisionOut,
    status_code=201,
)
async def create_architecture_decision_endpoint(
    body: ArchitectureDecisionCreate,
    session: AsyncSession = Depends(get_write_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    user: AuthenticatedUser = Depends(require_auth),
) -> ArchitectureDecisionOut:
    """The API never calls Voyage itself (CLAUDE.md: LLM/embedding calls
    stay server-side in the worker) — this only enqueues, exactly like
    POST /postmortems does for Phase 18's embed job."""
    decision = await create_architecture_decision(session, body, author_user_id=user.id)
    await arq_pool.enqueue_job("embed_architecture_decision", str(decision.id))
    return decision


@router.get(
    "/architecture-decisions/{decision_id}",
    response_model=ArchitectureDecisionOut,
    dependencies=[Depends(require_auth)],
)
async def get_architecture_decision_endpoint(
    decision_id: UUID, session: AsyncSession = Depends(get_read_session)
) -> ArchitectureDecisionOut:
    decision = await get_architecture_decision(session, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="architecture decision not found")
    return decision


@router.patch(
    "/architecture-decisions/{decision_id}",
    response_model=ArchitectureDecisionOut,
    dependencies=[Depends(require_auth)],
)
async def patch_architecture_decision_endpoint(
    decision_id: UUID,
    body: ArchitectureDecisionPatch,
    session: AsyncSession = Depends(get_write_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> ArchitectureDecisionOut:
    result = await patch_architecture_decision(session, decision_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="architecture decision not found")
    decision, should_reembed = result
    if should_reembed:
        await arq_pool.enqueue_job("embed_architecture_decision", str(decision.id))
    return decision


@router.delete(
    "/architecture-decisions/{decision_id}",
    status_code=204,
    dependencies=[Depends(require_auth)],
)
async def delete_architecture_decision_endpoint(
    decision_id: UUID, session: AsyncSession = Depends(get_write_session)
) -> Response:
    deleted = await delete_architecture_decision(session, decision_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="architecture decision not found")
    return Response(status_code=204)


# --- AI change records ----------------------------------------------------


@router.get(
    "/ai-change-records",
    response_model=PaginatedAiChangeRecords,
    dependencies=[Depends(require_auth)],
)
async def list_ai_change_records_endpoint(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    since: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_read_session),
) -> PaginatedAiChangeRecords:
    items, total = await list_ai_change_records(session, limit, offset, since=since)
    return PaginatedAiChangeRecords(items=items, limit=limit, offset=offset, total=total)


@router.get(
    "/ai-change-records/{record_id}",
    response_model=AiChangeRecordDetail,
    dependencies=[Depends(require_auth)],
)
async def get_ai_change_record_endpoint(
    record_id: UUID, session: AsyncSession = Depends(get_read_session)
) -> AiChangeRecordDetail:
    """Detail shape (Phase 23, docs/AI_NATIVE_PLAN.md): also carries
    linked_incident_ids and violations — a read-side addition over the
    base AiChangeRecordOut every other endpoint here still returns."""
    record = await get_ai_change_record_detail(session, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="AI change record not found")
    return record


@router.post("/ai-change-records", response_model=AiChangeRecordOut)
async def create_ai_change_record_endpoint(
    body: AiChangeRecordCreate,
    response: Response,
    session: AsyncSession = Depends(get_write_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    agent_or_user: AuthenticatedUser | None = Depends(require_auth_or_agent),
) -> AiChangeRecordOut:
    """201 for a genuinely new record, 200 (not a 409) when `commit_sha`
    already had one — re-POSTing for the same commit must be a safe
    no-op, per docs/AI_NATIVE_PLAN.md Phase 21's own acceptance criteria.
    `agent_or_user` is None on the automation-token path (the common
    case — this is what .claude/hooks/capture_ai_change.sh calls); when
    it's a real user, a human POSTed this by hand, which the API allows
    but doesn't expect to be the primary path."""
    author_user_id = agent_or_user.id if agent_or_user is not None else None
    record, created = await create_ai_change_record(session, body, author_user_id=author_user_id)
    response.status_code = 201 if created else 200
    if created:
        await arq_pool.enqueue_job("embed_ai_change_record", str(record.id))
    return record


# --- Invariant violations ----------------------------------------------


@router.post(
    "/invariant-violations",
    response_model=InvariantViolationOut,
    status_code=201,
)
async def create_invariant_violation_endpoint(
    body: InvariantViolationCreate,
    session: AsyncSession = Depends(get_write_session),
    _agent_or_user: AuthenticatedUser | None = Depends(require_auth_or_agent),
) -> InvariantViolationOut:
    """Phase 23 (docs/AI_NATIVE_PLAN.md): `.claude/hooks/check_invariants.sh`
    (Phase 22) calls this as a side effect of blocking an Edit/Write, not a
    replacement for it — the hook's own exit 2 happens either way,
    regardless of whether this call succeeds. `require_auth_or_agent`
    reused unchanged from Phase 21 (the same automation-token path
    .claude/hooks/capture_ai_change.sh already uses); no idempotency key
    here, unlike POST /ai-change-records's commit_sha — a violation is a
    point-in-time detection event, not a resource with a natural identity
    to dedupe against."""
    return await create_invariant_violation(session, body)
