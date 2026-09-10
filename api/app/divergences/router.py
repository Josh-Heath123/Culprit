"""`POST /divergences/captures` — Phase 29 field 9.

Mounted with no router-level auth dependency in app/main.py, like
`app/facts/router.py` and for the same reason: this one is gated by
`require_project_token` per route, because a project token is not a user
session and must not become usable anywhere a user session is expected.
Adding a GET here later needs its own decision about which credential
reads it — a CI token that can *write* findings is not automatically a
credential that should be able to *read* every finding in the system.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.divergences.dependencies import get_divergence_session
from app.divergences.schemas import DivergenceCapture, DivergencesAccepted
from app.divergences.service import (
    RejectedByDatabase,
    UnknownCapture,
    store_divergences,
)
from app.facts.dependencies import require_project_token

logger = structlog.get_logger("divergences")

router = APIRouter(prefix="/divergences", tags=["divergences"])


@router.post(
    "/captures",
    response_model=DivergencesAccepted,
    status_code=201,
    dependencies=[Depends(require_project_token)],
)
async def create_divergence_capture(
    payload: DivergenceCapture,
    session: AsyncSession = Depends(get_divergence_session),
) -> DivergencesAccepted:
    try:
        stored = await store_divergences(
            session, payload.divergences, payload.capture_id
        )
    except UnknownCapture as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RejectedByDatabase as exc:
        # 422 with the constraint's rule, never the row: a divergence
        # embeds two whole facts, and Postgres renders the failing row
        # into its own error text.
        logger.warning("divergences_rejected_by_database", constraint=exc.constraint)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "divergences_stored",
        first_seen=stored.first_seen,
        seen_again=stored.seen_again,
        suppressed=stored.suppressed,
        capture_id=str(payload.capture_id) if payload.capture_id else None,
    )
    return DivergencesAccepted(
        first_seen=stored.first_seen,
        seen_again=stored.seen_again,
        suppressed=stored.suppressed,
        stored_at=datetime.now(UTC),
    )
