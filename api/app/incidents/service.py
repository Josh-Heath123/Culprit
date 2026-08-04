"""DB queries for Phase 7's read endpoints — I/O only, no transformation
logic (see app/incidents/transforms.py for the pure ORM-row -> API-shape
mapping). Read-only throughout: the api-reader role (Phase 1) only has
SELECT, and nothing here needs more than that — the one write this phase
triggers (a new root-cause narrative) happens entirely inside the
worker's Phase 6 job under root-cause-writer, a different role. See
app/incidents/router.py's regenerate endpoint, which only enqueues.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import IncidentCandidate

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


async def list_incidents(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[IncidentCandidate], int]:
    total = (
        await session.execute(select(func.count()).select_from(IncidentCandidate))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(IncidentCandidate)
                .options(selectinload(IncidentCandidate.anomalies))
                .order_by(IncidentCandidate.opened_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def get_incident(session: AsyncSession, incident_id: UUID) -> IncidentCandidate | None:
    return (
        await session.execute(
            select(IncidentCandidate)
            .options(selectinload(IncidentCandidate.anomalies))
            .where(IncidentCandidate.id == incident_id)
        )
    ).scalar_one_or_none()
