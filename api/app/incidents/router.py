"""Phase 7 (minimal): the three endpoints Phase 8's dashboard needs.
GET /incidents (paginated), GET /incidents/{id} (detail), and
and, until Phase 32 part 2, POST /incidents/{id}/regenerate-root-cause —
removed with the narrative job it enqueued. Incidents are read-only
history from the earlier engine now (DIAGNOSTIC_PLAN.md Phase 32).

Deliberately minimal — no filtering, sorting options, or write endpoints
beyond the one action below. Extending this is Phase 7's own future
work, not something to grow opportunistically while building Phase 8.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.incidents.schemas import IncidentDetail, PaginatedIncidents
from app.incidents.service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    get_incident,
    get_linked_ai_change_records,
    list_incidents,
)
from app.incidents.transforms import incident_detail, incident_summary

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


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
    linked_records = await get_linked_ai_change_records(session, incident_id)
    return incident_detail(incident, linked_records)
