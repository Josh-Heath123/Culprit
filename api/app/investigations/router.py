"""`POST /investigations` and the reads — Phase 32, part 2.

The write takes the project token, like the other uploads a CI job or an
agent makes (`require_project_token`); the reads take a user session.
Declared per route, as in app/readings/router.py, so a route added here
later cannot inherit a credential nobody chose for it.

There is no `POST /investigations/{id}/probe` and no route that opens an
investigation: running a probe from here needs an agent, which arrives in
Phase 33. Investigations come from `culprit diagnose`, run where the
environment is.
"""

import structlog
from culprit_model.investigations import Investigation
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_auth
from app.facts.dependencies import require_project_token
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


@router.post(
    "",
    response_model=InvestigationStored,
    status_code=201,
    dependencies=[Depends(require_project_token)],
)
async def create_investigation(
    payload: Investigation,
    session: AsyncSession = Depends(get_investigation_writer_session),
) -> InvestigationStored:
    try:
        stored = await service.store(session, payload)
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
    return InvestigationTree.model_validate(service.tree(investigation))
