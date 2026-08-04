"""Drains otel-metrics/otel-logs Redis Streams into raw_events.

Runs as an arq cron job (see app/main.py), not a bare while-True loop.
Uses a Redis Streams consumer group so a crash mid-batch leaves those
messages unacked and redeliverable, not lost: each tick first reclaims
anything left pending from a prior crash (XREADGROUP id "0") before
reading new messages (id ">"). Writes are a single bulk INSERT per batch,
XACKed only once that insert has committed.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as redis
from culprit_shared.raw_event import RawEventIn
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import raw_events
from app.observability import instrument_job

logger = logging.getLogger("consumer")

STREAMS = ("otel-metrics", "otel-logs")
GROUP_NAME = "raw-events-drain"
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
LOCK_TTL_S = 30


async def ensure_consumer_groups(client: redis.Redis) -> None:
    for stream in STREAMS:
        try:
            await client.xgroup_create(stream, GROUP_NAME, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def _parse_entry(fields: dict) -> dict:
    # Validates against the exact same model api/app/ingest_gateway used
    # to serialize this entry onto the stream (see shared/culprit_shared)
    # instead of a hand-reimplemented dict of .get()s that could silently
    # drift from that contract.
    payload = json.loads(fields["data"])
    return RawEventIn.model_validate(payload).model_dump()


async def _drain_one(client: redis.Redis, engine: AsyncEngine, stream: str, start_id: str) -> int:
    response = await client.xreadgroup(
        groupname=GROUP_NAME,
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

    rows = [_parse_entry(fields) for _entry_id, fields in entries]
    async with engine.begin() as conn:
        await conn.execute(insert(raw_events), rows)

    await client.xack(stream, GROUP_NAME, *entry_ids)
    logger.info("inserted + acked %d rows from %s", len(rows), stream)
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
            recovered = await _drain_one(client, engine, stream, "0")
            fresh = await _drain_one(client, engine, stream, ">")
            totals[stream] = recovered + fresh
        return totals
    finally:
        await client.delete(LOCK_KEY)
