"""`GET /investigations/{id}/narration` — Phase 35 part 2.

Read-only, under a user session and `api-reader`. There is no write
route: only the worker's narrator writes a narration, under its own role.
The API never calls a provider and cannot ask for a narration; a
narration of a verification, or through `culprit mcp`, does not exist
(the phase's "Do NOT implement").
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_auth
from app.investigations import service as investigations
from app.investigations.dependencies import get_read_session
from app.narrations import service
from app.narrations.schemas import NarrationView

router = APIRouter(prefix="/investigations", tags=["narrations"])


@router.get(
    "/{investigation_id}/narration",
    response_model=NarrationView,
    dependencies=[Depends(require_auth)],
)
async def get_narration(
    investigation_id: str, session: AsyncSession = Depends(get_read_session)
) -> NarrationView:
    investigation = await investigations.load(session, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return await service.view(session, investigation)
