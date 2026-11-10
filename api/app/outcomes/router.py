"""`GET /outcomes/accuracy` — Phase 34 part 2.

Computed only from recorded verifications, per fault class and per source,
with every count beside the share (app/verifications/service.py,
`METHOD`). Read under `api-reader`, with a user session.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_auth
from app.investigations.dependencies import get_read_session
from app.verifications import service
from app.verifications.schemas import Accuracy

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


@router.get("/accuracy", response_model=Accuracy, dependencies=[Depends(require_auth)])
async def accuracy(session: AsyncSession = Depends(get_read_session)) -> Accuracy:
    return Accuracy.model_validate(await service.accuracy(session))
