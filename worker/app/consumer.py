"""Drains otel-metrics/otel-logs/otel-traces Redis Streams into Postgres.

Runs as arq cron jobs (see app/main.py), not a bare while-True loop.
Uses a Redis Streams consumer group per job so a crash mid-batch leaves
those messages unacked and redeliverable, not lost: each tick first
reclaims anything left pending from a prior crash (XREADGROUP id "0")
before reading new messages (id ">"). Writes are a single statement per
batch, XACKed only once that write has committed.

An entry that cannot be parsed is quarantined to DEAD_LETTER_STREAM and
acked (Phase 26) rather than raising out of the batch: before that, one
malformed message wedged the drain forever and every valid message
behind it stopped arriving.

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
from typing import NamedTuple

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

#: Where an entry that cannot be parsed goes (Phase 26,
#: docs/DIAGNOSTIC_PLAN.md). Before this, one malformed entry raised out
#: of the batch's list comprehension, nothing was acked, and the *same*
#: batch was reclaimed and failed again on every subsequent tick — a
#: single bad message wedged the drain permanently and silently, and
#: every valid message behind it stopped arriving. Quarantining and
#: acking is the only outcome that lets the good entries through.
DEAD_LETTER_STREAM = "dead-letter"

#: Capped so a persistently-malformed producer cannot grow Redis without
#: bound. Approximate trimming (Redis trims to a whole node boundary),
#: which is the cheap variant and precise enough for a diagnostic queue.
DEAD_LETTER_MAXLEN = 10_000


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


class DrainResult(NamedTuple):
    """What one batch did.

    `quarantined` is carried out of the drain rather than only logged so
    it reaches the job's return value, and from there the span and
    structured log `instrument_job` builds from it -- the same treatment
    `app/rag/job.py` gives its `dropped_citations`. A number that only
    exists inside a log format string is a number nobody alerts on.
    """

    written: int
    quarantined: int

    def __add__(self, other: "DrainResult") -> "DrainResult":  # type: ignore[override]
        return DrainResult(self.written + other.written, self.quarantined + other.quarantined)


_NOTHING_DRAINED = DrainResult(written=0, quarantined=0)


async def _drain_batch(
    client: redis.Redis,
    engine: AsyncEngine,
    stream: str,
    group: str,
    start_id: str,
    parse: Callable[[dict], dict],
    write: Callable[[AsyncEngine, list[dict]], Awaitable[None]],
) -> DrainResult:
    response = await client.xreadgroup(
        groupname=group,
        consumername=CONSUMER_NAME,
        streams={stream: start_id},
        count=BATCH_SIZE,
        block=None if start_id != ">" else 200,
    )
    if not response:
        return _NOTHING_DRAINED

    _stream_name, entries = response[0]
    if not entries:
        return _NOTHING_DRAINED

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

    rows, quarantined = await _parse_or_quarantine(client, stream, group, entries, parse)

    if not rows and len(entries) > 1:
        # Every entry in the batch failed. That is not "a corrupt
        # message", it is a systemic parse failure -- a gateway/worker
        # version skew mid-rollout, say, where RawEventIn has moved on
        # one side. Quarantining and acking the whole stream would
        # destroy real telemetry: DEAD_LETTER_MAXLEN is 10k entries, and
        # at the default 600/minute ingest rate the buffer wraps in under
        # twenty minutes, after which the data is simply gone.
        #
        # So raise instead. Nothing is acked, the entries stay in the
        # source stream, and the drain wedges -- which is the *old*,
        # recoverable behaviour, kept deliberately for exactly the case
        # where it is the right answer. A single bad message among good
        # ones still gets quarantined and acked; that is the fix. This is
        # only the all-or-nothing case.
        raise RuntimeError(
            f"every entry in a {len(entries)}-entry batch from {stream} failed to parse; "
            f"refusing to ack. This looks systemic (a schema/version skew), not a corrupt "
            f"message -- fix the cause and the batch will drain."
        )

    if rows:
        await write(engine, rows)

    # Acked only after both the write and the quarantine writes have
    # committed. A crash before this point redelivers the whole batch,
    # which is the existing at-least-once behaviour; a crash after a
    # quarantine xadd but before this ack re-quarantines the same entry,
    # which is a harmless duplicate in a diagnostic stream.
    await client.xack(stream, group, *entry_ids)
    logger.info(
        "wrote + acked %d rows from %s (%d quarantined)", len(rows), stream, quarantined
    )
    return DrainResult(written=len(rows), quarantined=quarantined)


async def _parse_or_quarantine(
    client: redis.Redis,
    stream: str,
    group: str,
    entries: list,
    parse: Callable[[dict], dict],
) -> tuple[list[dict], int]:
    """Parses each entry independently, sending the failures to
    DEAD_LETTER_STREAM rather than letting one of them take the batch
    down.

    Deliberately catching broad `Exception`: the failure modes here are
    a truncated JSON body, a payload from an older/newer gateway that no
    longer validates against `RawEventIn`, and anything else a corrupted
    stream entry can be. All of them mean the same thing operationally —
    this one entry is not processable and the other 199 in the batch
    should not be held hostage to it.
    """
    rows: list[dict] = []
    quarantined = 0
    for entry_id, fields in entries:
        try:
            rows.append(parse(fields))
        except Exception as exc:
            quarantined += 1
            logger.warning(
                "quarantining unparseable entry %s from %s: %s", entry_id, stream, exc
            )
            await client.xadd(
                DEAD_LETTER_STREAM,
                {
                    "source_stream": stream,
                    "source_group": group,
                    "source_entry_id": entry_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    # The original payload, verbatim — a quarantined
                    # entry is only useful if you can see what it was.
                    "data": fields.get("data", ""),
                },
                maxlen=DEAD_LETTER_MAXLEN,
                approximate=True,
            )
    return rows, quarantined


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
        quarantined = 0
        for stream in STREAMS:
            # Recover anything left pending from a prior crash first, then read new.
            recovered = await _drain_batch(
                client, engine, stream, GROUP_NAME, "0", _parse_raw_event, _write_raw_events
            )
            fresh = await _drain_batch(
                client, engine, stream, GROUP_NAME, ">", _parse_raw_event, _write_raw_events
            )
            result = recovered + fresh
            totals[stream] = result.written
            quarantined += result.quarantined
        # Reported alongside the per-stream write counts so it lands in
        # instrument_job's span and structured log, not only in a
        # logger.info format string nobody can alert on.
        if quarantined:
            totals["quarantined"] = quarantined
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
        result = recovered + fresh
        totals = {EDGES_STREAM: result.written}
        if result.quarantined:
            totals["quarantined"] = result.quarantined
        return totals
    finally:
        await client.delete(EDGES_LOCK_KEY)
