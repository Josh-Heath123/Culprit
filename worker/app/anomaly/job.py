"""arq cron job: scores new metric-type raw_events and persists anomalies.

Wiring only — the statistics live in scorer.py (pure, no I/O). This
module's job is: pull new rows since the watermark, route each to its
(service_name, metric_name) scorer, persist scorer state + the watermark,
and write an anomalies row for anything crossing the threshold. No
correlation, no RAG, no API exposure — see Phase 5/6/7.
"""

import logging
from datetime import timedelta

import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.anomaly.scorer import ANOMALY_THRESHOLD, MetricScorer, is_anomalous
from app.anomaly.state import load_scorer, load_watermark, save_progress
from app.db import raw_events
from app.observability import instrument_job

logger = logging.getLogger("anomaly")

#: How many new raw_events rows to pull per run. Generous relative to
#: this demo's traffic volume.
BATCH_SIZE = 2000

#: anomalies.time_window (Phase 1) is a tstzrange, not a foreign key into
#: raw_events (see api/app/db/models.py::Anomaly — TimescaleDB advises
#: against FKs into a hypertable) — this pads a small, symmetric window
#: around the single flagged point, since one metric observation doesn't
#: have a natural start/end of its own.
ANOMALY_WINDOW_PAD = timedelta(seconds=1)

_INSERT_ANOMALY_SQL = text(
    "INSERT INTO anomalies "
    "(service_name, metric_name, score, threshold, detected_at, time_window) "
    "VALUES (:service_name, :metric_name, :score, :threshold, :detected_at, "
    "tstzrange(:window_start, :window_end))"
)


@instrument_job("score_new_metrics")
async def score_new_metrics(ctx: dict) -> dict:
    redis_client: redis.Redis = ctx["anomaly_redis"]
    engine: AsyncEngine = ctx["anomaly_engine"]

    watermark = await load_watermark(redis_client)

    query = (
        select(
            raw_events.c.id,
            raw_events.c.time,
            raw_events.c.service_name,
            raw_events.c.metric_name,
            raw_events.c.value,
        )
        .where(raw_events.c.event_type == "metric")
        .where(raw_events.c.id > watermark)
        .order_by(raw_events.c.id)
        .limit(BATCH_SIZE)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()

    if not rows:
        return {"scored": 0, "anomalies": 0}

    scorers: dict[tuple[str, str], MetricScorer] = {}
    anomaly_rows: list[dict] = []
    max_id = watermark

    for row in rows:
        max_id = max(max_id, row.id)
        if row.metric_name is None or row.value is None:
            continue

        key = (row.service_name, row.metric_name)
        scorer = scorers.get(key)
        if scorer is None:
            scorer = await load_scorer(redis_client, row.service_name, row.metric_name)

        z = scorer.update(row.value)
        scorers[key] = scorer

        if z is not None and is_anomalous(z):
            anomaly_rows.append(
                {
                    "service_name": row.service_name,
                    "metric_name": row.metric_name,
                    "score": z,
                    "threshold": ANOMALY_THRESHOLD,
                    "detected_at": row.time,
                    "window_start": row.time - ANOMALY_WINDOW_PAD,
                    "window_end": row.time + ANOMALY_WINDOW_PAD,
                }
            )

    # DB write before Redis persistence, deliberately: if the anomalies
    # insert fails, the watermark/scorer state stay unchanged, so the next
    # run reprocesses this exact batch from the same starting state and
    # retries — safe, since scoring is deterministic. Persisting Redis
    # state first and having the DB write fail afterward would silently
    # drop these anomalies forever (the events would already be behind
    # the advanced watermark).
    if anomaly_rows:
        async with engine.begin() as conn:
            await conn.execute(_INSERT_ANOMALY_SQL, anomaly_rows)

    await save_progress(redis_client, scorers, max_id)

    logger.info("scored %d metric events, flagged %d anomalies", len(rows), len(anomaly_rows))
    return {"scored": len(rows), "anomalies": len(anomaly_rows)}
