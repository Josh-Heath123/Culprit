"""pgvector cosine-similarity retrieval (Phase 6: postmortems; Phase 21,
docs/AI_NATIVE_PLAN.md: generalized across postmortems/architecture_
decisions/ai_change_records).

Plain SQL against the same Postgres instance used for time-series data —
no separate vector DB, per docs/ARCHITECTURE.md's storage layer (one Postgres instance).
Read-only: embedding writes live in worker/app/rag/embed_job.py (the live
job path) and worker/scripts/seed_postmortems.py (a one-off
fixture-loading script for postmortems specifically).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import ai_change_records, architecture_decisions, postmortems

#: Fixed at 3 per Phase 6's scope — top-3 similar postmortems, not a
#: configurable retrieval depth. retrieve_similar_records (Phase 21)
#: keeps the same default.
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
    """Unchanged since Phase 6 — worker/app/rag/job.py's existing
    root-cause grounding still calls this directly, and Phase 21
    deliberately doesn't touch that job (docs/AI_NATIVE_PLAN.md
    invariant 11). retrieve_similar_records below is a separate,
    additive generalization, not a replacement for this."""
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


RecordType = Literal["postmortem", "decision", "ai_change"]

#: Default search scope for retrieve_similar_records, and the only three
#: values RecordType accepts — see docs/AI_NATIVE_PLAN.md Phase 21's own
#: "family of records" framing.
ALL_RECORD_TYPES: tuple[RecordType, ...] = ("postmortem", "decision", "ai_change")


@dataclass(frozen=True)
class RetrievedRecord:
    id: UUID
    record_type: RecordType
    title: str
    body: str
    similarity: float


def _select_for(record_type: RecordType, query_embedding: list[float]) -> Select:
    """One SELECT per table, each shaped identically (id, record_type
    literal, title, body, similarity) so union_all below can combine them
    — `ai_change_records` has no `title` column at all, so its
    `commit_sha` stands in for one here, matching worker/app/db.py's own
    comment on that table."""
    if record_type == "postmortem":
        table, title_col, body_col = postmortems, postmortems.c.title, postmortems.c.body
    elif record_type == "decision":
        table, title_col, body_col = (
            architecture_decisions,
            architecture_decisions.c.title,
            architecture_decisions.c.body,
        )
    else:
        table, title_col, body_col = (
            ai_change_records,
            ai_change_records.c.commit_sha,
            ai_change_records.c.summary,
        )

    distance = table.c.embedding.cosine_distance(query_embedding)
    return (
        select(
            table.c.id,
            literal(record_type).label("record_type"),
            title_col.label("title"),
            body_col.label("body"),
            (1 - distance).label("similarity"),
        )
        .where(table.c.embedding.is_not(None))
    )


async def retrieve_similar_records(
    conn: AsyncConnection,
    query_embedding: list[float],
    top_k: int = TOP_K,
    record_types: Sequence[RecordType] = ALL_RECORD_TYPES,
) -> list[RetrievedRecord]:
    """The Phase 21 generalization: a UNION ALL across whichever of the
    three tables `record_types` names (all three by default), ranked
    together by similarity and cut to `top_k` overall — not `top_k` per
    table. `embedding IS NOT NULL` still excludes pending/failed rows on
    every branch, same as retrieve_similar_postmortems above."""
    if not record_types:
        raise ValueError("record_types must name at least one record type")

    combined = union_all(*(_select_for(rt, query_embedding) for rt in record_types)).subquery()
    rows = (
        await conn.execute(
            select(combined).order_by(combined.c.similarity.desc()).limit(top_k)
        )
    ).all()
    return [
        RetrievedRecord(
            id=row.id,
            record_type=row.record_type,
            title=row.title,
            body=row.body,
            similarity=row.similarity,
        )
        for row in rows
    ]
