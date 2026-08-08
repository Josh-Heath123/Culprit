"""Drains otel-metrics/otel-logs/otel-traces Redis Streams into Postgres.

Runs as arq cron jobs (see app/main.py), not a bare while-True loop.
Uses a Redis Streams consumer group per job so a crash mid-batch leaves
those messages unacked and redeliverable, not lost: each tick first
reclaims anything left pending from a prior crash (XREADGROUP id "0")
before reading new messages (id ">"). Writes are a single statement per
batch, XACKed only once that write has committed.

drain_streams (raw_events, unchanged since Phase 3) and drain_edges
(observed_service_edges, Phase 19) share the read/recover/ack mechanics
via _drain_batch but not the write step — a plain bulk INSERT for
raw_events, an aggregated UPSERT for edges — so each gets its own small
parse/write pair instead of forcing one write shape to fit both.
"""

import asyncio
import json
import logging
import os
from collections import Counter
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from culprit_shared.raw_event import RawEventIn
from culprit_shared.service_edge import ServiceEdgeObservation
from sqlalchemy import func, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import observed_service_edges, raw_events
from app.observability import instrument_job

logger = logging.getLogger("consumer")

STREAMS = ("otel-metrics", "otel-logs")
GROUP_NAME = "raw-events-drain"
EDGES_STREAM = "otel-traces"
EDGES_GROUP_NAME = "service-edges-drain"
# Fixed, not random-per-run: recovering our own pending entries after a
# restart depends on reconnecting under the same consumer identity.
CONSUMER_NAME = "drain-1"
BATCH_SIZE = 200

# Guards against overlapping ticks if a drain ever takes longer than the
# cron interval (a slow DB, a big backlog): without this, two overlapping
# invocations would both read the same still-unacked pending entries and
# insert them twice — not the crash-recovery duplication a real crash can
# cause, but a second, avoidable duplication path on top of it. The TTL
# ensures a crash while holding the lock doesn't deadlock the job forever.
LOCK_KEY = "raw-events-drain:lock"
EDGES_LOCK_KEY = "service-edges-drain:lock"
LOCK_TTL_S = 30


_STREAM_GROUPS = [(stream, GROUP_NAME) for stream in STREAMS] + [(EDGES_STREAM, EDGES_GROUP_NAME)]


async def ensure_consumer_groups(client: redis.Redis) -> None:
    for stream, group in _STREAM_GROUPS:
        try:
            await client.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def _parse_raw_event(fields: dict) -> dict:
    # Validates against the exact same model api/app/ingest_gateway used
    # to serialize this entry onto the stream (see shared/culprit_shared)
    # instead of a hand-reimplemented dict of .get()s that could silently
    # drift from that contract.
    payload = json.loads(fields["data"])
    return RawEventIn.model_validate(payload).model_dump()


def _parse_edge(fields: dict) -> dict:
    payload = json.loads(fields["data"])
    return ServiceEdgeObservation.model_validate(payload).model_dump()


async def _write_raw_events(engine: AsyncEngine, rows: list[dict]) -> None:
    async with engine.begin() as conn:
        await conn.execute(insert(raw_events), rows)


def _aggregate_edge_counts(rows: list[dict]) -> list[dict]:
    """Collapses a batch of individual edge observations down to one row
    per unique (from_service, to_service) pair, with `observations` set
    to however many times that pair appeared in *this* batch — not a
    loop of single +1 upserts. Whether the gateway sent one stream entry
    per span (today's design) or ever pre-aggregates them doesn't matter:
    this collapses either shape correctly. Pure and DB-free specifically
    so this is unit-testable without a database — see
    worker/tests/test_edge_upsert.py."""
    counts = Counter((row["from_service"], row["to_service"]) for row in rows)
    return [
        {"from_service": from_service, "to_service": to_service, "observations": count}
        for (from_service, to_service), count in counts.items()
    ]


async def _write_edges(engine: AsyncEngine, rows: list[dict]) -> None:
    """`first_seen_at` is untouched on conflict — only its column-level
    server_default fires, on first insert."""
    stmt = pg_insert(observed_service_edges).values(_aggregate_edge_counts(rows))
    stmt = stmt.on_conflict_do_update(
        index_elements=["from_service", "to_service"],
        set_={
            "observations": observed_service_edges.c.observations + stmt.excluded.observations,
            "last_seen_at": func.now(),
        },
    )
    async with engine.begin() as conn:
        await conn.execute(stmt)


async def _drain_batch(
    client: redis.Redis,
    engine: AsyncEngine,
    stream: str,
    group: str,
    start_id: str,
    parse: Callable[[dict], dict],
    write: Callable[[AsyncEngine, list[dict]], Awaitable[None]],
) -> int:
    response = await client.xreadgroup(
        groupname=group,
        consumername=CONSUMER_NAME,
        streams={stream: start_id},
        count=BATCH_SIZE,
        block=None if start_id != ">" else 200,
    )
    if not response:
        return 0

    _stream_name, entries = response[0]
    if not entries:
        return 0

    entry_ids = [entry_id for entry_id, _fields in entries]
    logger.info(
        "claimed %d messages from %s (ids %s..%s), start_id=%s",
        len(entries),
        stream,
        entry_ids[0],
        entry_ids[-1],
        start_id,
    )

    crash_test_delay = float(os.environ.get("DRAIN_SIMULATED_DELAY_S", "0"))
    if crash_test_delay:
        logger.info("DRAIN_SIMULATED_DELAY_S=%s: sleeping before insert", crash_test_delay)
        await asyncio.sleep(crash_test_delay)

    rows = [parse(fields) for _entry_id, fields in entries]
    await write(engine, rows)

    await client.xack(stream, group, *entry_ids)
    logger.info("wrote + acked %d rows from %s", len(rows), stream)
    return len(rows)


@instrument_job("drain_streams")
async def drain_streams(ctx: dict) -> dict[str, int]:
    client: redis.Redis = ctx["redis"]
    engine: AsyncEngine = ctx["engine"]

    got_lock = await client.set(LOCK_KEY, CONSUMER_NAME, nx=True, ex=LOCK_TTL_S)
    if not got_lock:
        logger.info("skipping tick: a previous drain is still running")
        return {}

    try:
        totals: dict[str, int] = {}
        for stream in STREAMS:
            # Recover anything left pending from a prior crash first, then read new.
            recovered = await _drain_batch(
                client, engine, stream, GROUP_NAME, "0", _parse_raw_event, _write_raw_events
            )
            fresh = await _drain_batch(
                client, engine, stream, GROUP_NAME, ">", _parse_raw_event, _write_raw_events
            )
            totals[stream] = recovered + fresh
        return totals
    finally:
        await client.delete(LOCK_KEY)


@instrument_job("drain_edges")
async def drain_edges(ctx: dict) -> dict[str, int]:
    """Phase 19: same crash-recovery mechanics as drain_streams, its own
    consumer group and lock (a stuck/slow edges drain must never block
    raw_events, and vice versa) — see app/main.py's cron schedule for how
    the two are staggered."""
    client: redis.Redis = ctx["redis"]
    engine: AsyncEngine = ctx["engine"]

    got_lock = await client.set(EDGES_LOCK_KEY, CONSUMER_NAME, nx=True, ex=LOCK_TTL_S)
    if not got_lock:
        logger.info("skipping tick: a previous edges drain is still running")
        return {}

    try:
        recovered = await _drain_batch(
            client, engine, EDGES_STREAM, EDGES_GROUP_NAME, "0", _parse_edge, _write_edges
        )
        fresh = await _drain_batch(
            client, engine, EDGES_STREAM, EDGES_GROUP_NAME, ">", _parse_edge, _write_edges
        )
        return {EDGES_STREAM: recovered + fresh}
    finally:
        await client.delete(EDGES_LOCK_KEY)
