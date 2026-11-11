"""`POST` and `GET /investigations/{id}/verifications` — Phase 34 part 2.

The write takes the project token (CI posting what `culprit verify`
wrote) or an agent's signature (an agent posting the verification it ran),
and records which, as `POST /investigations` does; the read takes a user
session. Declared per route, so a route added here later cannot inherit a
credential nobody chose for it.

A verification is its own append-only record. Posting one never writes to
the investigation it points at.
"""

from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.dependencies import (
    Submitter,
    body_documented_as,
    require_project_token_or_agent,
    submitted_body,
)
from app.auth.dependencies import require_auth
from app.investigations import service as investigations
from app.investigations.dependencies import get_read_session
from app.verifications import service
from app.verifications.schemas import (
    StoredVerification,
    VerificationList,
    VerificationStored,
    VerificationSubmitted,
)

logger = structlog.get_logger("verifications")
router = APIRouter(prefix="/investigations", tags=["verifications"])

_submitted = submitted_body(VerificationSubmitted)


async def get_verification_writer_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = (
        request.app.state.verification_writer_session_factory
    )
    async with factory() as session:
        yield session


@router.post(
    "/{investigation_id}/verifications",
    response_model=VerificationStored,
    status_code=201,
    openapi_extra=body_documented_as(VerificationSubmitted),
)
async def create_verification(
    investigation_id: str,
    body: VerificationSubmitted = Depends(_submitted),
    submitter: Submitter = Depends(require_project_token_or_agent),
    reader: AsyncSession = Depends(get_read_session),
    writer: AsyncSession = Depends(get_verification_writer_session),
) -> VerificationStored:
    verification = body.verification
    if submitter.agent is not None:
        # An agent posts only what it measured: every run is its own.
        mine = submitter.agent.id
        named = {run.agent_id for rerun in verification.reran for run in rerun.runs}
        if named - {mine}:
            logger.warning("verification_refused_other_agent", agent=mine)
            raise HTTPException(
                status_code=403, detail="every run must name the agent that signed the request"
            )
    investigation = await investigations.load(reader, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    try:
        service.check_against(investigation, verification)
    except service.Refused as exc:
        logger.warning("verification_refused", investigation=investigation_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    earlier = await service.source_of(reader, investigation_id)
    if earlier is not None and earlier != body.source:
        raise HTTPException(
            status_code=409,
            detail=f"{investigation_id}'s verifications record its fault as {earlier}; "
            f"one investigation's fault cannot also be {body.source}",
        )
    clean = service.sanitised(verification)
    try:
        await service.store(writer, clean, body.source, submitter.label)
    except service.AlreadyStored as exc:
        raise HTTPException(
            status_code=409, detail=f"verification {clean.id} is already stored"
        ) from exc
    logger.info(
        "verification_stored",
        investigation=investigation_id,
        verification=clean.id,
        verdict=clean.verdict.value,
        source=body.source,
    )
    return VerificationStored(id=clean.id, verdict=clean.verdict.value)


@router.get(
    "/{investigation_id}/verifications",
    response_model=VerificationList,
    dependencies=[Depends(require_auth)],
)
async def list_verifications(
    investigation_id: str, session: AsyncSession = Depends(get_read_session)
) -> VerificationList:
    if await investigations.load(session, investigation_id) is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    rows = await service.list_for(session, investigation_id)
    return VerificationList(
        investigation_id=investigation_id, items=[StoredVerification(**row) for row in rows]
    )
