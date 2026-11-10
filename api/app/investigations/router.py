"""`POST /investigations` and the reads — Phase 32, part 2.

The write takes the project token (CI posting what `culprit diagnose`
wrote) or an agent's signature (an agent posting its own walk), and records
which (`investigations.submitted_by`, Phase 33 part 2); the reads take a
user session.
Declared per route, as in app/readings/router.py, so a route added here
later cannot inherit a credential nobody chose for it.

There is no `POST /investigations/{id}/probe`: a stored investigation is a
final record (Phase 32.1, and the Phase 33 part 1 review). Probing again is
a new agent task; diagnosing again, a new investigation.
"""

import structlog
from culprit_model.investigations import Investigation
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dependencies import (
    Submitter,
    body_documented_as,
    require_project_token_or_agent,
    submitted_body,
)
from app.auth.dependencies import require_auth
from app.investigations import service
from app.investigations.dependencies import (
    get_investigation_writer_session,
    get_read_session,
)
from app.investigations.schemas import (
    InvestigationList,
    InvestigationStored,
    InvestigationSummary,
    InvestigationTree,
)

logger = structlog.get_logger("investigations")
router = APIRouter(prefix="/investigations", tags=["investigations"])

#: The investigation, parsed once its submitter is authenticated.
_investigation = submitted_body(Investigation)


@router.post(
    "",
    response_model=InvestigationStored,
    status_code=201,
    openapi_extra=body_documented_as(Investigation),
)
async def create_investigation(
    payload: Investigation = Depends(_investigation),
    submitter: Submitter = Depends(require_project_token_or_agent),
    session: AsyncSession = Depends(get_investigation_writer_session),
) -> InvestigationStored:
    if submitter.agent is not None:
        # An agent posts only its own walk: every reading in it is its own.
        mine = submitter.agent.id
        named = {held.reading.agent_id for held in payload.readings}
        others = sorted(named - {mine})
        if others:
            logger.warning("investigation_refused_other_agent", agent=submitter.agent.id)
            raise HTTPException(
                status_code=403, detail="every reading must name the agent that signed the request"
            )
    try:
        stored = await service.store(session, payload, submitter.label)
    except service.AlreadyStored as exc:
        raise HTTPException(
            status_code=409, detail=f"investigation {payload.id} is already stored"
        ) from exc
    except service.RejectedByDatabase as exc:
        logger.warning("investigation_rejected_by_database", constraint=exc.constraint)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info(
        "investigation_stored",
        investigation=stored.id,
        complete=stored.diagnosis.complete if stored.diagnosis else None,
    )
    return InvestigationStored(
        id=stored.id, readings=len(stored.readings), fault_edges=len(stored.fault_tree)
    )


@router.get("", response_model=InvestigationList, dependencies=[Depends(require_auth)])
async def list_investigations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_read_session),
) -> InvestigationList:
    rows = await service.list_investigations(session, limit, offset)
    return InvestigationList(
        items=[InvestigationSummary(**row) for row in rows], limit=limit, offset=offset
    )


@router.get(
    "/{investigation_id}", response_model=Investigation, dependencies=[Depends(require_auth)]
)
async def get_investigation(
    investigation_id: str, session: AsyncSession = Depends(get_read_session)
) -> Investigation:
    investigation = await service.load(session, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return investigation


@router.get(
    "/{investigation_id}/tree",
    response_model=InvestigationTree,
    dependencies=[Depends(require_auth)],
)
async def get_investigation_tree(
    investigation_id: str, session: AsyncSession = Depends(get_read_session)
) -> InvestigationTree:
    investigation = await service.load(session, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    submitter = await service.submitted_by(session, investigation_id) or "project-token"
    return InvestigationTree.model_validate(service.tree(investigation, submitter))
