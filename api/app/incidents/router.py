"""Phase 7 (minimal): the three endpoints Phase 8's dashboard needs.
GET /incidents (paginated), GET /incidents/{id} (detail), and
POST /incidents/{id}/regenerate-root-cause (re-triggers Phase 6).

Deliberately minimal — no filtering, sorting options, or write endpoints
beyond the one action below. Extending this is Phase 7's own future
work, not something to grow opportunistically while building Phase 8.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.incidents.limiter import limiter
from app.incidents.schemas import IncidentDetail, PaginatedIncidents
from app.incidents.service import DEFAULT_LIMIT, MAX_LIMIT, get_incident, list_incidents
from app.incidents.transforms import incident_detail, incident_summary

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_arq_pool(request: Request) -> ArqRedis:
    return request.app.state.arq_pool


@router.get("", response_model=PaginatedIncidents)
async def list_incidents_endpoint(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PaginatedIncidents:
    rows, total = await list_incidents(session, limit, offset)
    return PaginatedIncidents(
        items=[incident_summary(row) for row in rows], limit=limit, offset=offset, total=total
    )


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident_endpoint(
    incident_id: UUID, session: AsyncSession = Depends(get_session)
) -> IncidentDetail:
    incident = await get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident_detail(incident)


@router.post("/{incident_id}/regenerate-root-cause", status_code=202)
@limiter.limit("5/minute")
async def regenerate_root_cause_endpoint(
    request: Request,
    incident_id: UUID,
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> dict:
    """Only enqueues — never writes to incident_candidates itself (see
    app/incidents/service.py's module docstring on why the api-reader
    role stays read-only). The existing narrative, if any, stays visible
    and marked 'ready' until the worker's Phase 6 job overwrites it with
    the new one; the frontend surfaces the in-flight regenerate via its
    own mutation state, not a server-side 'regenerating' status."""
    incident = await get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    await arq_pool.enqueue_job("generate_root_cause_narrative", str(incident_id))
    return {"status": "enqueued", "incident_id": str(incident_id)}
