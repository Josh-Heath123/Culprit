"""arq jobs: embed_postmortem (Phase 18), embed_architecture_decision and
embed_ai_change_record (Phase 21, docs/AI_NATIVE_PLAN.md) — all three
thin wrappers over `_embed_record` below, which holds the shared
rate-limit/retry/write logic. Extracted without changing
`embed_postmortem`'s own observable behaviour — the existing
`worker/tests/test_embed_job.py` postmortem test cases are the regression
guard for that (docs/AI_NATIVE_PLAN.md Phase 21 Known Trap 5): if any of
them needed to change to keep passing, this refactor changed something it
shouldn't have.

Event-driven, not a cron job (same reasoning as app/rag/job.py): enqueued
directly by api/app/postmortems/router.py and api/app/memory/router.py on
create, and on an update that actually changes the embedded text (or a
failed record being retried) — never on a schedule.

Each record's embedding is computed from exactly one column —
`postmortems.body`/`architecture_decisions.body`/`ai_change_records.
summary` — never a title. `ai_change_records` has no `title` column at
all; `summary` (the commit message) is the only text these records embed.

This module lives in app.rag and must not import app.anomaly or
app.correlation, same as app/rag/job.py — enforced by the import-linter
contract in pyproject.toml for the anomaly<->rag pair (there is no
separate contract for rag<->correlation, so this is enforced by design
discipline here, not tooling, for that specific pair).

Rate-limit handling (docs/SELF_HOSTED_PLAN.md Phase 18, Known Trap
context): Voyage's free tier returns RateLimitError at 3 requests/minute,
and a burst of writes *will* hit it. Do NOT copy
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
from sqlalchemy import Column, Table, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from voyageai.error import RateLimitError

from app.db import ai_change_records, architecture_decisions, postmortems
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


async def _embed_record(
    ctx: dict, table: Table, text_column: Column, record_id: str, *, kind: str
) -> dict:
    engine: AsyncEngine = ctx["rag_engine"]
    record_uuid = UUID(record_id)

    async with engine.connect() as conn:
        text = (
            await conn.execute(select(text_column).where(table.c.id == record_uuid))
        ).scalar_one_or_none()

    if text is None:
        logger.warning("%s %s vanished before embedding ran", kind, record_id)
        return {"status": "skipped", "reason": f"{kind}_not_found"}

    try:
        embedding = await embed_document(text)
    except RateLimitError as exc:
        await _write_error(engine, table, record_uuid, f"Voyage rate limit: {exc}")
        defer = _defer_seconds(ctx["job_try"])
        logger.warning(
            "%s %s embedding rate-limited (attempt %d), retrying in %ds: %s",
            kind,
            record_id,
            ctx["job_try"],
            defer,
            exc,
        )
        raise Retry(defer=defer) from exc
    except Exception as exc:
        await _write_error(engine, table, record_uuid, str(exc) or exc.__class__.__name__)
        raise

    async with engine.begin() as conn:
        await conn.execute(
            update(table)
            .where(table.c.id == record_uuid)
            .values(embedding=embedding, embedded_at=datetime.now(UTC), embedding_error=None)
        )

    logger.info("embedded %s %s", kind, record_id)
    return {"status": "embedded", f"{kind}_id": record_id}


async def _write_error(engine: AsyncEngine, table: Table, record_uuid: UUID, message: str) -> None:
    """Writes embedding_error unconditionally on any failure — including
    ones arq is about to retry — so the UI shows "failed" the moment a
    problem happens rather than staying silently "pending" until every
    retry is exhausted. A subsequent successful attempt (whether an arq
    retry or a user-triggered manual retry) always clears this."""
    async with engine.begin() as conn:
        await conn.execute(
            update(table).where(table.c.id == record_uuid).values(embedding_error=message)
        )


@instrument_job("embed_postmortem")
async def embed_postmortem(ctx: dict, postmortem_id: str) -> dict:
    return await _embed_record(
        ctx, postmortems, postmortems.c.body, postmortem_id, kind="postmortem"
    )


@instrument_job("embed_architecture_decision")
async def embed_architecture_decision(ctx: dict, decision_id: str) -> dict:
    return await _embed_record(
        ctx,
        architecture_decisions,
        architecture_decisions.c.body,
        decision_id,
        kind="architecture_decision",
    )


@instrument_job("embed_ai_change_record")
async def embed_ai_change_record(ctx: dict, record_id: str) -> dict:
    return await _embed_record(
        ctx, ai_change_records, ai_change_records.c.summary, record_id, kind="ai_change_record"
    )
