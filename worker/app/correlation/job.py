"""arq cron job: correlates recent anomalies into incident_candidates.

Wiring only — the graph logic lives in graph.py (pure, no I/O). Pure
rule-based logic throughout: no LLM anywhere in this phase. Per
CLAUDE.md, a wrong automated correlation here is the failure mode that
makes the whole product untrustworthy, so every decision below is a
deterministic rule, not a judgment call.

The one exception, and it's deliberately *not* a correlation decision:
when this job creates a brand-new incident_candidate (never when it
merely extends an existing one), it enqueues Phase 6's root-cause job by
name via arq — event-driven, not a second cron job polling for new
incidents. This module never imports app.rag (see the import-linter
contract in pyproject.toml); dispatch is by string job name only, so
correlation stays ignorant of what Phase 6 actually does.
"""

import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.correlation.graph import (
    CORRELATION_WINDOW,
    AnomalyNode,
    build_graph,
    connected_components,
)
from app.db import (
    anomalies,
    incident_anomalies,
    incident_candidates,
    service_dependencies,
    services,
)
from app.observability import instrument_job

logger = logging.getLogger("correlation")

#: Look back further than the correlation window itself so a chain of
#: anomalies straddling the window boundary isn't missed — an anomaly at
#: t-4min and one at t+1min are within CORRELATION_WINDOW of each other,
#: but pulling only the last CORRELATION_WINDOW of data could clip one
#: side of that pair.
LOOKBACK = CORRELATION_WINDOW * 2

#: How long a loaded adjacency stays cached in-process before this job
#: queries services/service_dependencies again. Phase 14: adjacency now
#: lives in the DB, not a hardcoded import, but re-querying it every
#: 5-second tick for data that changes maybe once a day is wasted work.
#: A service added mid-minute correlates one tick late until this
#: expires — acceptable; the alternative (query every tick) is not
#: meaningfully more correct, just more load.
_ADJACENCY_CACHE_TTL_S = 60.0
_adjacency_cache: dict[str, frozenset[str]] | None = None
_adjacency_cached_at: float = 0.0


async def _load_adjacency(engine: AsyncEngine) -> dict[str, frozenset[str]]:
    global _adjacency_cache, _adjacency_cached_at
    now = time.monotonic()
    if _adjacency_cache is not None and now - _adjacency_cached_at < _ADJACENCY_CACHE_TTL_S:
        return _adjacency_cache

    async with engine.connect() as conn:
        name_rows = (await conn.execute(select(services.c.id, services.c.name))).all()
        dep_rows = (
            await conn.execute(
                select(service_dependencies.c.from_service_id, service_dependencies.c.to_service_id)
            )
        ).all()

    id_to_name = {row.id: row.name for row in name_rows}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for from_id, to_id in dep_rows:
        from_name = id_to_name.get(from_id)
        to_name = id_to_name.get(to_id)
        if from_name is not None and to_name is not None:
            adjacency[from_name].add(to_name)

    _adjacency_cache = {name: frozenset(targets) for name, targets in adjacency.items()}
    _adjacency_cached_at = now
    return _adjacency_cache


@instrument_job("correlate_recent_anomalies")
async def correlate_recent_anomalies(ctx: dict) -> dict:
    engine: AsyncEngine = ctx["correlation_engine"]
    now = datetime.now(UTC)
    since = now - LOOKBACK

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(anomalies.c.id, anomalies.c.service_name, anomalies.c.detected_at)
                .where(anomalies.c.detected_at >= since)
                .order_by(anomalies.c.detected_at)
            )
        ).all()

    created = extended = conflicts = 0

    if rows:
        nodes = [
            AnomalyNode(id=row.id, service_name=row.service_name, detected_at=row.detected_at)
            for row in rows
        ]
        node_by_id = {node.id: node for node in nodes}
        adjacency = await _load_adjacency(engine)
        components = connected_components(build_graph(nodes, adjacency))

        for component in components:
            # Each component gets its own transaction: a failure
            # processing one component (or an unexpected exception) must
            # not roll back other components' already-successful work
            # from the same run.
            new_incident_id: uuid.UUID | None = None
            async with engine.begin() as conn:
                # The lookback window re-pulls anomalies from prior runs
                # too (there's no incremental watermark here — see
                # module docstring), so most of a component may already
                # be attached to something. Only anomalies never attached
                # to ANY incident (open or closed) are actually new work;
                # skip entirely if there's nothing new; among the new
                # ones, decide by which OPEN incidents the *already
                # attached* anomalies belong to.
                already_attached = await _already_attached_anomalies(conn, component)
                new_anomaly_ids = component - already_attached

                if not new_anomaly_ids:
                    continue

                open_incidents = await _open_incidents_for(conn, already_attached)

                if len(open_incidents) == 0:
                    # Either nothing in this component has ever been
                    # attached anywhere, or everything it was attached to
                    # has since closed. Either way, the new anomalies
                    # start a fresh incident — a closed incident stays
                    # closed; a genuinely new correlated anomaly opens a
                    # new one rather than silently reopening old history.
                    new_incident_id = await _create_incident(conn, new_anomaly_ids, node_by_id)
                    created += 1
                elif len(open_incidents) == 1:
                    await _extend_incident(
                        conn, next(iter(open_incidents)), new_anomaly_ids, node_by_id
                    )
                    extended += 1
                else:
                    # Explicit simplification: this component would
                    # require merging two or more already-separate open
                    # incident candidates into one. That's real
                    # graph-merge complexity for a rare edge case in a
                    # 3-service demo — log it and leave the existing
                    # incidents separate rather than guessing which one
                    # should absorb the new anomalies. They stay
                    # unattached and get reconsidered next run.
                    logger.warning(
                        "component with %d new anomalies spans %d existing open "
                        "incidents (%s) — leaving separate, not merging",
                        len(new_anomaly_ids),
                        len(open_incidents),
                        open_incidents,
                    )
                    conflicts += 1

            # Outside the transaction on purpose: the incident row is
            # already committed by this point, so a failure to enqueue
            # (e.g. Redis briefly unavailable) doesn't roll back real
            # correlation work — it just means that one incident never
            # gets a root-cause narrative, which is a Phase 6 concern,
            # not this job's.
            if new_incident_id is not None:
                await _enqueue_root_cause_job(ctx, new_incident_id)

    closed = await _close_stale_incidents(engine, now)

    logger.info(
        "considered %d anomalies: %d new incidents, %d extended, "
        "%d merge conflicts skipped, %d closed",
        len(rows),
        created,
        extended,
        conflicts,
        closed,
    )
    return {
        "anomalies_considered": len(rows),
        "created": created,
        "extended": extended,
        "conflicts": conflicts,
        "closed": closed,
    }


async def _already_attached_anomalies(
    conn: AsyncConnection, anomaly_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    rows = (
        await conn.execute(
            select(incident_anomalies.c.anomaly_id)
            .where(incident_anomalies.c.anomaly_id.in_(anomaly_ids))
            .distinct()
        )
    ).all()
    return {row.anomaly_id for row in rows}


async def _open_incidents_for(
    conn: AsyncConnection, anomaly_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not anomaly_ids:
        return set()
    rows = (
        await conn.execute(
            select(incident_anomalies.c.incident_id)
            .join(
                incident_candidates,
                incident_candidates.c.id == incident_anomalies.c.incident_id,
            )
            .where(incident_anomalies.c.anomaly_id.in_(anomaly_ids))
            .where(incident_candidates.c.closed_at.is_(None))
            .distinct()
        )
    ).all()
    return {row.incident_id for row in rows}


async def _create_incident(
    conn: AsyncConnection, new_anomaly_ids: set[uuid.UUID], node_by_id: dict[uuid.UUID, AnomalyNode]
) -> uuid.UUID:
    detected_times = [node_by_id[anomaly_id].detected_at for anomaly_id in new_anomaly_ids]
    incident_id = uuid.uuid4()
    await conn.execute(
        incident_candidates.insert().values(
            id=incident_id,
            opened_at=min(detected_times),
            last_anomaly_at=max(detected_times),
            closed_at=None,
            status="open",
        )
    )
    await _attach(conn, incident_id, new_anomaly_ids)
    return incident_id


async def _enqueue_root_cause_job(ctx: dict, incident_id: uuid.UUID) -> None:
    """Event-driven trigger for Phase 6, called only when a NEW incident
    was just created above — never on extend. Dispatches by job name
    (arq's ArqRedis.enqueue_job), not by importing app.rag.job directly,
    so this module has zero coupling to what Phase 6 does with it.
    """
    rag_pool = ctx.get("rag_pool")
    if rag_pool is None:
        logger.warning(
            "rag_pool not configured on ctx; skipping root-cause enqueue for incident %s",
            incident_id,
        )
        return
    await rag_pool.enqueue_job("generate_root_cause_narrative", str(incident_id))


async def _extend_incident(
    conn: AsyncConnection,
    incident_id: uuid.UUID,
    new_anomaly_ids: set[uuid.UUID],
    node_by_id: dict[uuid.UUID, AnomalyNode],
) -> None:
    detected_times = [node_by_id[anomaly_id].detected_at for anomaly_id in new_anomaly_ids]
    await conn.execute(
        update(incident_candidates)
        .where(incident_candidates.c.id == incident_id)
        .values(
            last_anomaly_at=func.greatest(
                incident_candidates.c.last_anomaly_at, max(detected_times)
            )
        )
    )
    await _attach(conn, incident_id, new_anomaly_ids)


async def _attach(
    conn: AsyncConnection, incident_id: uuid.UUID, anomaly_ids: set[uuid.UUID]
) -> None:
    """Idempotent: ON CONFLICT DO NOTHING on the composite PK makes a
    re-attach a no-op instead of an error, though callers now only ever
    pass genuinely new (never-attached) anomaly ids.
    """
    stmt = pg_insert(incident_anomalies).values(
        [{"incident_id": incident_id, "anomaly_id": anomaly_id} for anomaly_id in anomaly_ids]
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["incident_id", "anomaly_id"])
    await conn.execute(stmt)


async def _close_stale_incidents(engine: AsyncEngine, now: datetime) -> int:
    """An incident closes once its most recent attached anomaly is older
    than the correlation window — nothing new has correlated into it
    recently. closed_at is derived from last_anomaly_at + the window
    (a fixed, data-determined instant), not wall-clock `now`, so it
    doesn't depend on incidental job-scheduling timing.
    """
    cutoff = now - CORRELATION_WINDOW
    async with engine.begin() as conn:
        result = await conn.execute(
            update(incident_candidates)
            .where(incident_candidates.c.closed_at.is_(None))
            .where(incident_candidates.c.last_anomaly_at < cutoff)
            .values(
                closed_at=incident_candidates.c.last_anomaly_at + CORRELATION_WINDOW,
                status="resolved",
            )
        )
    return result.rowcount
