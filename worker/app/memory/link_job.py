"""arq cron job: links recently-opened incidents to AI change records that
plausibly caused them (Phase 23, docs/AI_NATIVE_PLAN.md) — the second half
of "wiring the flywheel," alongside .claude/hooks/check_invariants.sh's
own violation-persisting edit (Phase 22 -> Phase 21).

Pure rule-based logic throughout, no LLM anywhere in this module (invariant
8, CLAUDE.md's "Where the AI must stay deterministic" section): a fixed
30-minute lookback before the incident opened, plus a deliberately crude
substring match between an incident's service names and a change record's
changed file paths. This only *annotates* an incident that already
exists — it never changes which anomalies get grouped into which incident
(worker/app/correlation/'s own concern, untouched here).

Imports only app.db (Core tables) and app.observability, the same way
worker/app/rag/context.py reads incident_candidates/anomalies without
importing app.correlation: this job needs correlation's *output* (the DB
rows), never its *code*. The third importlinter contract (worker/
pyproject.toml) makes this structural, not just a convention — see that
file's own comment for why it's deliberately one-directional.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import (
    ai_change_records,
    anomalies,
    incident_anomalies,
    incident_candidates,
    incident_change_links,
)
from app.observability import instrument_job

logger = logging.getLogger("memory.link_job")

#: Fixed, not configurable (Out of scope: "a configurable ... threshold
#: exposed anywhere" is explicitly ruled out for this phase) — a change
#: record links only if committed at or before the incident's opened_at,
#: and no more than this far before it.
AI_CHANGE_LOOKBACK = timedelta(minutes=30)

#: How far back to re-scan "recently opened" incidents each tick.
#: Comfortably larger than AI_CHANGE_LOOKBACK itself so a missed or
#: delayed tick never causes a real match to be skipped — re-scanning an
#: incident already fully processed is cheap and safe (Known Trap 3):
#: the composite primary key on incident_change_links makes a repeat
#: insert attempt a no-op via ON CONFLICT DO NOTHING, the same idiom
#: worker/app/correlation/job.py::_attach already uses for
#: incident_anomalies. Not itself a per-incident precision window — the
#: 30-minute lookback above is what actually decides a match, this only
#: bounds how much history gets re-considered on every tick.
INCIDENT_RESCAN_WINDOW = timedelta(hours=1)


def _normalize_service_name(service_name: str) -> str:
    """Services are named 'order-service'; demo-services directories are
    'order_service' — see demo-services/order_service, inventory_service,
    payments_service. Hyphens normalize to underscores, not the other
    direction, since file paths are the substring-search haystack."""
    return service_name.replace("-", "_")


def _matching_file(service_name: str, files_changed: list[str]) -> str | None:
    """Returns the first changed-file path whose text contains the
    (normalized) service name, or None. Deliberately crude and literal —
    not fuzzy, not a real path-component match (Known Trap 2): a
    heuristic that occasionally misses a real correlation is a far
    smaller problem than one that confidently links unrelated things."""
    normalized = _normalize_service_name(service_name)
    for path in files_changed:
        if normalized in path:
            return path
    return None


def _link_reason(
    service_name: str, file_path: str, opened_at: datetime, committed_at: datetime
) -> str:
    minutes = max(0, round((opened_at - committed_at).total_seconds() / 60))
    return f"{service_name} anomaly {minutes}m after a change touching {file_path}"


async def _incident_service_names(conn: AsyncConnection, incident_id: uuid.UUID) -> set[str]:
    rows = (
        await conn.execute(
            select(anomalies.c.service_name)
            .join(incident_anomalies, incident_anomalies.c.anomaly_id == anomalies.c.id)
            .where(incident_anomalies.c.incident_id == incident_id)
            .distinct()
        )
    ).all()
    return {row.service_name for row in rows}


async def _candidate_change_records(conn: AsyncConnection, opened_at: datetime) -> Sequence[Row]:
    return (
        await conn.execute(
            select(
                ai_change_records.c.id,
                ai_change_records.c.files_changed,
                ai_change_records.c.committed_at,
            )
            .where(ai_change_records.c.committed_at >= opened_at - AI_CHANGE_LOOKBACK)
            .where(ai_change_records.c.committed_at <= opened_at)
        )
    ).all()


@instrument_job("link_recent_changes")
async def link_recent_changes(ctx: dict) -> dict:
    engine: AsyncEngine = ctx["correlation_engine"]
    now = datetime.now(UTC)

    async with engine.connect() as conn:
        incident_rows = (
            await conn.execute(
                select(incident_candidates.c.id, incident_candidates.c.opened_at).where(
                    incident_candidates.c.opened_at >= now - INCIDENT_RESCAN_WINDOW
                )
            )
        ).all()

    links_created = 0
    for incident_row in incident_rows:
        # Each incident gets its own transaction, matching
        # worker/app/correlation/job.py's own per-component isolation: a
        # failure linking one incident must not roll back another
        # incident's already-successful links from the same run.
        async with engine.begin() as conn:
            service_names = await _incident_service_names(conn, incident_row.id)
            if not service_names:
                continue

            change_rows = await _candidate_change_records(conn, incident_row.opened_at)
            if not change_rows:
                continue

            for change_row in change_rows:
                files_changed = list(change_row.files_changed or [])
                match: tuple[str, str] | None = None
                for service_name in sorted(service_names):
                    file_path = _matching_file(service_name, files_changed)
                    if file_path is not None:
                        match = (service_name, file_path)
                        break
                if match is None:
                    continue

                service_name, file_path = match
                reason = _link_reason(
                    service_name, file_path, incident_row.opened_at, change_row.committed_at
                )
                stmt = pg_insert(incident_change_links).values(
                    incident_id=incident_row.id,
                    ai_change_record_id=change_row.id,
                    link_reason=reason,
                )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["incident_id", "ai_change_record_id"]
                )
                result = await conn.execute(stmt)
                if result.rowcount:
                    links_created += 1

    logger.info(
        "considered %d recently-opened incident(s): %d link(s) created",
        len(incident_rows),
        links_created,
    )
    return {"incidents_considered": len(incident_rows), "links_created": links_created}
