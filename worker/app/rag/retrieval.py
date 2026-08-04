"""pgvector cosine-similarity retrieval over postmortems (Phase 6).

Plain SQL against the same Postgres instance used for time-series data —
no separate vector DB, per CLAUDE.md's "one database, two roles" rule.
Read-only: embedding writes live in worker/scripts/seed_postmortems.py, a
one-off fixture-loading script, not the live job path this module is
part of.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import postmortems

#: Fixed at 3 per Phase 6's scope — top-3 similar postmortems, not a
#: configurable retrieval depth.
TOP_K = 3


@dataclass(frozen=True)
class RetrievedPostmortem:
    id: UUID
    title: str
    body: str
    similarity: float


async def retrieve_similar_postmortems(
    conn: AsyncConnection, query_embedding: list[float], top_k: int = TOP_K
) -> list[RetrievedPostmortem]:
    distance = postmortems.c.embedding.cosine_distance(query_embedding)
    rows = (
        await conn.execute(
            select(
                postmortems.c.id,
                postmortems.c.title,
                postmortems.c.body,
                (1 - distance).label("similarity"),
            )
            .where(postmortems.c.embedding.is_not(None))
            .order_by(distance)
            .limit(top_k)
        )
    ).all()
    return [
        RetrievedPostmortem(id=row.id, title=row.title, body=row.body, similarity=row.similarity)
        for row in rows
    ]
