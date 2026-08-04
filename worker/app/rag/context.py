"""Builds a text summary of one incident_candidate for Phase 6: which
services were involved, which metrics were anomalous and by how much, and
a sample of raw log lines from the incident's time window.

I/O only (DB reads) — no embedding calls, no LLM calls, and no anomaly-
detection or correlation logic. By the time this runs, Phase 4 and Phase
5 have already decided what's anomalous and what's correlated; this
module only reads their output and describes it. See app/rag/embeddings.py
and app/rag/llm.py for the modules that actually call out to Voyage/Claude.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import anomalies, incident_anomalies, incident_candidates, raw_events
from app.rag.sanitize import truncate

#: Padding around [opened_at, last_anomaly_at] when pulling log context —
#: wider than anomalies.time_window's own +/-1s pad (app/anomaly/job.py),
#: since the goal here is surrounding narrative context for a human/LLM
#: reader, not a precise anomaly-scoring window.
LOG_WINDOW_PAD = timedelta(seconds=30)

#: How many raw log lines to pull as "representative" context. Kept
#: small on purpose — this is a narrative aid for one LLM call, not a
#: debugging dump (per CLAUDE.md: don't dump raw ingested logs into
#: context; query/aggregate a specific window instead).
MAX_LOG_MESSAGES = 12

#: Per-message cap when folding log lines into the embedding-query text —
#: independent of, and smaller than, the LLM-prompt cap in app/rag/llm.py,
#: since this text only ever reaches an embedding model, not something
#: that follows instructions.
MAX_LOG_MESSAGE_CHARS_FOR_EMBEDDING = 200


@dataclass(frozen=True)
class AnomalySummary:
    service_name: str
    metric_name: str
    score: float
    detected_at: datetime


@dataclass(frozen=True)
class IncidentContext:
    incident_id: UUID
    opened_at: datetime
    last_anomaly_at: datetime
    services: list[str]
    anomaly_summaries: list[AnomalySummary]
    #: Raw, NOT yet sanitized/delimited — callers that pass this to an
    #: LLM prompt (app/rag/llm.py) are responsible for that; callers that
    #: only build an embedding-query string (render_embedding_text below)
    #: don't need to, since embeddings don't follow instructions.
    log_messages: list[str]


async def build_incident_context(
    conn: AsyncConnection, incident_id: UUID
) -> IncidentContext | None:
    incident_row = (
        await conn.execute(
            select(
                incident_candidates.c.id,
                incident_candidates.c.opened_at,
                incident_candidates.c.last_anomaly_at,
            ).where(incident_candidates.c.id == incident_id)
        )
    ).first()
    if incident_row is None:
        return None

    anomaly_rows = (
        await conn.execute(
            select(
                anomalies.c.service_name,
                anomalies.c.metric_name,
                anomalies.c.score,
                anomalies.c.detected_at,
            )
            .join(incident_anomalies, incident_anomalies.c.anomaly_id == anomalies.c.id)
            .where(incident_anomalies.c.incident_id == incident_id)
            .order_by(anomalies.c.detected_at)
        )
    ).all()

    summaries = [
        AnomalySummary(row.service_name, row.metric_name, row.score, row.detected_at)
        for row in anomaly_rows
    ]
    services = sorted({s.service_name for s in summaries})

    window_start = incident_row.opened_at - LOG_WINDOW_PAD
    window_end = incident_row.last_anomaly_at + LOG_WINDOW_PAD

    log_messages: list[str] = []
    if services:
        log_rows = (
            await conn.execute(
                select(raw_events.c.message)
                .where(raw_events.c.event_type == "log")
                .where(raw_events.c.service_name.in_(services))
                .where(raw_events.c.time >= window_start)
                .where(raw_events.c.time <= window_end)
                .where(raw_events.c.message.is_not(None))
                .order_by(raw_events.c.time)
                .limit(MAX_LOG_MESSAGES)
            )
        ).all()
        log_messages = [row.message for row in log_rows if row.message]

    return IncidentContext(
        incident_id=incident_row.id,
        opened_at=incident_row.opened_at,
        last_anomaly_at=incident_row.last_anomaly_at,
        services=services,
        anomaly_summaries=summaries,
        log_messages=log_messages,
    )


def render_embedding_text(context: IncidentContext) -> str:
    """Pure — the short text description embedded to build the retrieval
    query (app/rag/embeddings.py + app/rag/retrieval.py). Distinct from
    what's sent to the LLM prompt (app/rag/llm.py builds that separately),
    though both draw on the same IncidentContext.
    """
    lines = [f"Incident involving services: {', '.join(context.services)}."]
    for summary in context.anomaly_summaries:
        lines.append(
            f"Anomalous metric {summary.metric_name} on {summary.service_name}: "
            f"z-score {summary.score:.2f} at {summary.detected_at.isoformat()}."
        )
    for message in context.log_messages:
        lines.append(f"Log: {truncate(message, MAX_LOG_MESSAGE_CHARS_FOR_EMBEDDING)}")
    return "\n".join(lines)
