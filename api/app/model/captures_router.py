"""`/captures` — Phase 30 field 9: `POST /captures`, `GET /captures/{id}`,
`GET /captures/diff?a=&b=`.

Mounted in app/main.py with no router-level dependency, like the other
capture routers, because the two directions need different credentials:
`POST` takes the project token a CI job or `culprit env capture` runner
holds (never a user session), and the two `GET`s take a user session
(any role — the same audience as the rest of the dashboard's reads).
Declaring each per route means a new endpoint here cannot inherit a
credential nobody chose for it.

The CLI does not call `POST /captures` itself; see docs/LIMITS.md ("The
CLI does not upload anything").
"""

from collections.abc import AsyncIterator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.dependencies import require_auth
from app.facts.dependencies import require_project_token
from app.facts.service import DuplicateCapture, MismatchedCaptureId, RejectedByDatabase
from app.model.captures import UngrantedFact, diff, fact_out, get_capture, store_capture
from app.model.captures_schemas import (
    CaptureAccepted,
    CaptureDetail,
    CaptureDiff,
    CaptureFactOut,
)
from app.model.envelope import Envelope, EnvelopeRejected, open_envelope

logger = structlog.get_logger("captures")

router = APIRouter(prefix="/captures", tags=["captures"])


async def get_capture_writer_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.capture_session_factory
    async with factory() as session:
        yield session


async def get_reader_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


@router.post(
    "",
    response_model=CaptureAccepted,
    status_code=201,
    dependencies=[Depends(require_project_token)],
)
async def create_capture(
    envelope: Envelope,
    session: AsyncSession = Depends(get_capture_writer_session),
) -> CaptureAccepted:
    try:
        opened = open_envelope(envelope)
        capture = await store_capture(session, opened)
    except (EnvelopeRejected, UngrantedFact, MismatchedCaptureId) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateCapture as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RejectedByDatabase as exc:
        logger.warning("capture_rejected_by_database", constraint=exc.constraint)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "configured_capture_stored",
        capture_id=str(capture.id),
        environment=capture.environment,
        facts=len(opened.bundle.facts),
        refused=len(opened.bundle.refused),
        signed=opened.signed_by is not None,
    )
    return CaptureAccepted(
        capture_id=capture.id,
        environment=capture.environment or "",
        digest=opened.digest,
        signed_by=opened.signed_by,
        facts_stored=len(opened.bundle.facts),
        refused=len(opened.bundle.refused),
    )


# Declared before `/{capture_id}`, or FastAPI would try to parse "diff"
# as a UUID and answer 422 for a route that exists.
@router.get("/diff", response_model=CaptureDiff, dependencies=[Depends(require_auth)])
async def diff_captures(
    a: UUID = Query(...),
    b: UUID = Query(...),
    session: AsyncSession = Depends(get_reader_session),
) -> CaptureDiff:
    left = await get_capture(session, a)
    right = await get_capture(session, b)
    if left is None or right is None:
        raise HTTPException(status_code=404, detail="no CONFIGURED capture with that id")
    return CaptureDiff(
        a=a,
        b=b,
        a_environment=left[0].environment or "",
        b_environment=right[0].environment or "",
        entries=diff(left[1], right[1]),
    )


@router.get("/{capture_id}", response_model=CaptureDetail, dependencies=[Depends(require_auth)])
async def read_capture(
    capture_id: UUID,
    session: AsyncSession = Depends(get_reader_session),
) -> CaptureDetail:
    found = await get_capture(session, capture_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no CONFIGURED capture with that id")
    capture, facts = found
    return CaptureDetail(
        capture_id=capture.id,
        environment=capture.environment or "",
        extractor=capture.extractor,
        started_at=capture.started_at,
        finished_at=capture.finished_at,
        digest=capture.digest,
        signed_by=capture.signed_by,
        grants=capture.grants or [],
        refused=capture.refused or [],
        facts=[CaptureFactOut(**fact_out(row)) for row in facts],
    )
