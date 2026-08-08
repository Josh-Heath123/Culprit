"""arq job: embed_postmortem — Phase 18, postmortem write path.

Event-driven, not a cron job (same reasoning as app/rag/job.py): enqueued
directly by api/app/postmortems/router.py on POST /postmortems and on
PATCH /postmortems/{id} when the body actually changed (or a failed
postmortem is being retried) — never on a schedule.

A postmortem's embedding is computed from `body` alone (matching
worker/scripts/seed_postmortems.py's embed_document(seed.body) call) —
this job never touches `title`.

This module lives in app.rag and must not import app.anomaly or
app.correlation, same as app/rag/job.py — enforced by the import-linter
contract in pyproject.toml for the anomaly<->rag pair (there is no
separate contract for rag<->correlation, so this is enforced by design
discipline here, not tooling, for that specific pair).

Rate-limit handling (docs/SELF_HOSTED_PLAN.md Phase 18, Known Trap
context): Voyage's free tier returns RateLimitError at 3 requests/minute,
and a burst of postmortem writes *will* hit it. Do NOT copy
seed_postmortems.py's unconditional 21-second sleep here — that pacing is
right for a one-off backfill script, not for blocking this job (and by
extension every other job this worker process needs to run) on a fixed
wait per attempt. Instead: on any failure, write the error string (so the
UI shows "failed" immediately, never a silently-stuck "pending" row) and
raise arq's own Retry with an increasing defer, so a burst of writes
naturally spreads out across Voyage's per-minute window instead of
hammering it in a tight loop or blocking the worker's other cron jobs
while waiting.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from arq import Retry
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from voyageai.error import RateLimitError

from app.db import postmortems
from app.observability import instrument_job
from app.rag.embeddings import embed_document

logger = logging.getLogger("rag")

#: Seconds to wait before the next attempt, scaled by which attempt this
#: is (ctx["job_try"], 1-indexed) — 20s, 40s, 60s, capped at 60s. Voyage's
#: limit is per-minute, so anything beyond a minute of backoff buys
#: nothing further; capping also bounds how stale a "failed" row's retry
#: schedule can get for a very bursty write spike.
_BASE_DEFER_S = 20
_MAX_DEFER_S = 60


def _defer_seconds(job_try: int) -> int:
    return min(_MAX_DEFER_S, _BASE_DEFER_S * job_try)


@instrument_job("embed_postmortem")
async def embed_postmortem(ctx: dict, postmortem_id: str) -> dict:
    engine: AsyncEngine = ctx["rag_engine"]
    postmortem_uuid = UUID(postmortem_id)

    async with engine.connect() as conn:
        body = (
            await conn.execute(
                select(postmortems.c.body).where(postmortems.c.id == postmortem_uuid)
            )
        ).scalar_one_or_none()

    if body is None:
        logger.warning("postmortem %s vanished before embedding ran", postmortem_id)
        return {"status": "skipped", "reason": "postmortem_not_found"}

    try:
        embedding = await embed_document(body)
    except RateLimitError as exc:
        await _write_error(engine, postmortem_uuid, f"Voyage rate limit: {exc}")
        defer = _defer_seconds(ctx["job_try"])
        logger.warning(
            "postmortem %s embedding rate-limited (attempt %d), retrying in %ds: %s",
            postmortem_id,
            ctx["job_try"],
            defer,
            exc,
        )
        raise Retry(defer=defer) from exc
    except Exception as exc:
        await _write_error(engine, postmortem_uuid, str(exc) or exc.__class__.__name__)
        raise

    async with engine.begin() as conn:
        await conn.execute(
            update(postmortems)
            .where(postmortems.c.id == postmortem_uuid)
            .values(embedding=embedding, embedded_at=datetime.now(UTC), embedding_error=None)
        )

    logger.info("embedded postmortem %s", postmortem_id)
    return {"status": "embedded", "postmortem_id": postmortem_id}


async def _write_error(engine: AsyncEngine, postmortem_uuid: UUID, message: str) -> None:
    """Writes embedding_error unconditionally on any failure — including
    ones arq is about to retry — so the UI shows "failed" the moment a
    problem happens rather than staying silently "pending" until every
    retry is exhausted. A subsequent successful attempt (whether an arq
    retry or a user-triggered manual retry) always clears this."""
    async with engine.begin() as conn:
        await conn.execute(
            update(postmortems)
            .where(postmortems.c.id == postmortem_uuid)
            .values(embedding_error=message)
        )
