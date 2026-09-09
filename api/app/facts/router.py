"""`POST /facts/captures` — Phase 28 field 9.

Mounted with no router-level auth dependency in app/main.py, unlike
every other router: this one is gated by `require_project_token` per
route, because a project token is not a user session and must not be
usable anywhere a user session is expected. Adding a GET here later
would need its own explicit decision about which credential reads it.
"""

import structlog
from culprit_model.protocol import CaptureBundle
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.facts.dependencies import get_fact_session, require_project_token
from app.facts.schemas import CaptureAccepted
from app.facts.service import (
    DuplicateCapture,
    MismatchedCaptureId,
    RejectedByDatabase,
    UnsupportedPlane,
    store_capture,
)

logger = structlog.get_logger("facts")

router = APIRouter(prefix="/facts", tags=["facts"])


@router.post(
    "/captures",
    response_model=CaptureAccepted,
    status_code=201,
    dependencies=[Depends(require_project_token)],
)
async def create_capture(
    bundle: CaptureBundle,
    session: AsyncSession = Depends(get_fact_session),
) -> CaptureAccepted:
    try:
        capture = await store_capture(session, bundle)
    except UnsupportedPlane as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MismatchedCaptureId as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DuplicateCapture as exc:
        # 409, not 500. The client derives `capture_id` from the capture's
        # own content and time, so a retry of a request that already
        # succeeded is a normal event and its answer is "you already sent
        # this", not a traceback.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RejectedByDatabase as exc:
        # 422, and the detail names the constraint's rule rather than the
        # row. Postgres's own message carries `DETAIL: Failing row
        # contains (...)`, which for a config fact is the value it
        # refused — see RejectedByDatabase.
        logger.warning("capture_rejected_by_database", constraint=exc.constraint)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "capture_stored",
        capture_id=str(capture.id),
        extractor=capture.extractor,
        facts=len(bundle.facts),
        skipped=len(bundle.skipped),
    )
    return CaptureAccepted(
        capture_id=capture.id,
        plane=capture.plane,
        extractor=capture.extractor,
        started_at=capture.started_at,
        finished_at=capture.finished_at,  # pyright: ignore[reportArgumentType]
        facts_stored=len(bundle.facts),
        skipped=len(bundle.skipped),
    )
