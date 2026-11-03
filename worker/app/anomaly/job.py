"""arq cron job: scores new metric-type raw_events and persists anomalies.

Wiring only — the statistics live in scorer.py (pure, no I/O). This
module's job is: pull new rows since the watermark, route each to its
(service_name, metric_name) scorer, persist scorer state + the watermark,
and write an anomalies row for anything crossing the threshold. No
correlation, no RAG, no API exposure — see Phase 5/6/7.

Phase 31 adds a second output beside the first: an **impedance reading**
(`probe.edge.impedance`) on the OBSERVED plane, for each scored row that
can be attributed to a connection. Nothing was removed to make room — an
`anomalies` row and a reading answer different questions. An anomaly says
"this metric on this service is unusual"; a reading says "here is what was
measured at this edge, at this moment, and here is the verdict", which is
the form the diagnostic engine compares and the form a divergence can
later be built from.

`scorer.py` and `state.py` are untouched by this: the statistics do not
change, only what is written down about them.
"""

import logging
import os
import time
from datetime import timedelta
from typing import Any
from uuid import uuid4

import redis.asyncio as redis
from culprit_model.capabilities import Capability
from culprit_model.readings import Reading, Verdict
from culprit_model.subjects import build as build_subject
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.anomaly.scorer import (
    ANOMALY_THRESHOLD,
    MIN_OBSERVATIONS,
    MetricScorer,
    is_anomalous,
)
from app.anomaly.state import load_scorer, load_watermark, save_progress
from app.db import components, connections, raw_events, readings
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

#: The probe whose manifest these readings claim to come from. Mirrored
#: from `cli/internal/probe/observe_probes.go` — `effect: observe`,
#: `capabilities: [telemetry.metrics.read]`, `produces` a
#: `connection:{from}->{to}` subject with predicate `impedance`. The
#: worker is not the binary, but it produces the same probe's readings,
#: and a reading that named a probe id nobody could look up would be
#: unexplainable in exactly the way §2.6 exists to prevent.
IMPEDANCE_PROBE_ID = "probe.edge.impedance"
IMPEDANCE_PROBE_VERSION = 1

#: Who took the measurement. Not a hostname: several worker replicas are
#: one agent as far as a reading's provenance is concerned, and a
#: hostname would make the same measurement look like it came from
#: somewhere new every deploy.
IMPEDANCE_AGENT_ID = "culprit-worker"

#: Which environment these readings describe. An env var rather than a
#: derived value because the worker cannot know: it sees metric rows, and
#: nothing in a metric row says whether the service that emitted it was
#: staging or production. Defaulted, not required, because it is a label
#: rather than a credential — and "production" is the honest default for
#: a deployed worker, which is the only place this runs.
IMPEDANCE_ENVIRONMENT = os.environ.get("CULPRIT_ENVIRONMENT", "production")

#: Attribute keys a metric row may carry naming the service on the other
#: end of the call. The first two are OTel's `peer.service` in its dotted
#: and underscored spellings; `server.address` is the newer semantic
#: convention. Checked in this order, first hit wins.
_PEER_ATTRIBUTE_KEYS = ("peer.service", "peer_service", "server.address")

#: How long a loaded monitored_metrics map stays cached in-process before
#: re-querying `components` (`services` until Phase 27 renamed it).
#: Phase 14: a real third-party service can export
#: hundreds of metrics, and without this allowlist every single one gets
#: its own persistent EWMA scorer in Redis forever. Same reasoning as
#: worker/app/correlation/job.py's adjacency cache -- a service's
#: monitored_metrics changing mid-minute is picked up one tick late,
#: which is fine for a setting nobody expects to take effect instantly.
_METRICS_CACHE_TTL_S = 60.0
_monitored_metrics_cache: dict[str, list[str]] | None = None
_monitored_metrics_cached_at: float = 0.0

#: Same cache discipline, same TTL, for the declared inbound connections
#: attribution rule (b) needs. Topology changing mid-minute is picked up
#: one tick late, which is fine for a setting nobody expects to take
#: effect instantly.
_inbound_cache: dict[str, tuple[str, ...]] | None = None
_inbound_cached_at: float = 0.0


async def _load_monitored_metrics(engine: AsyncEngine) -> dict[str, list[str]]:
    global _monitored_metrics_cache, _monitored_metrics_cached_at
    now = time.monotonic()
    if (
        _monitored_metrics_cache is not None
        and now - _monitored_metrics_cached_at < _METRICS_CACHE_TTL_S
    ):
        return _monitored_metrics_cache

    async with engine.connect() as conn:
        rows = (
            await conn.execute(select(components.c.name, components.c.monitored_metrics))
        ).all()

    _monitored_metrics_cache = {row.name: row.monitored_metrics for row in rows}
    _monitored_metrics_cached_at = now
    return _monitored_metrics_cache


def _metric_allowed(metric_name: str, allowlist: list[str]) -> bool:
    """An empty allowlist means "score every metric seen for this
    service" -- the pre-Phase-14 behaviour, and also what a service with
    no registry row (registration lagging ingestion, or a fresh install
    still backfilling) gets by falling back to `[]` at the call site."""
    return not allowlist or metric_name in allowlist


async def _load_inbound_connections(engine: AsyncEngine) -> dict[str, tuple[str, ...]]:
    """`{to_component_name: (from_component_name, ...)}` from `connections`.

    Deduplicated by component pair, not by row. A connection's identity is
    `(from, to, kind)` (Phase 27), so orders-api may reach payments-api
    over both HTTP and a queue — two rows, one upstream. Counting rows
    would make rule (b) below decline to attribute a metric that has
    exactly one possible source.
    """
    global _inbound_cache, _inbound_cached_at
    now = time.monotonic()
    if _inbound_cache is not None and now - _inbound_cached_at < _METRICS_CACHE_TTL_S:
        return _inbound_cache

    source = components.alias("source")
    target = components.alias("target")
    query = select(source.c.name.label("from_name"), target.c.name.label("to_name")).select_from(
        connections.join(source, connections.c.from_component_id == source.c.id).join(
            target, connections.c.to_component_id == target.c.id
        )
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()

    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(row.to_name, set()).add(row.from_name)
    _inbound_cache = {name: tuple(sorted(sources)) for name, sources in grouped.items()}
    _inbound_cached_at = now
    return _inbound_cache


def _peer_from_attributes(attributes: Any, known_components: set[str]) -> str | None:
    """The peer service a metric row names, if it names a known one.

    "Known" is the whole point of the check: an attribute value is
    whatever the instrumented service put there, and a subject built from
    an unregistered name would describe a connection that exists in no
    model — unjoinable, and indistinguishable from a typo.
    """
    if not isinstance(attributes, dict):
        return None
    for key in _PEER_ATTRIBUTE_KEYS:
        value = attributes.get(key)
        if isinstance(value, str) and value in known_components:
            return value
    return None


def _impedance_target(
    service_name: str,
    attributes: Any,
    known_components: set[str],
    inbound: dict[str, tuple[str, ...]],
) -> str | None:
    """Which connection this metric row is a measurement of, or None.

    Three branches, in order, and the third is the one that matters:

    (a) The row names a peer, and that peer is a known component. The
        measurement is of `service -> peer`, which is what the service
        itself said it was talking to — the best evidence available.
    (b) No peer named, but the model declares exactly one inbound
        connection `X -> service`. There is only one edge the measurement
        could be about, so attributing it is not a guess.
    (c) Anything else — no peer and zero or several declared upstreams.
        **No reading is emitted.** A reading attributed to the wrong edge
        is worse than a missing one: it is a measurement that looks real,
        and the whole OBSERVED plane is worth nothing if a row in it might
        be about something else. The anomaly row is still written either
        way, so nothing is lost, only left unattributed.
    """
    peer = _peer_from_attributes(attributes, known_components)
    if peer is not None:
        return build_subject("connection", from_component=service_name, to_component=peer)

    sources = inbound.get(service_name, ())
    if len(sources) == 1:
        return build_subject("connection", from_component=sources[0], to_component=service_name)

    return None


def _impedance_reading(
    target: str, metric_name: str, deviation: float | None, samples: int, taken_at: Any
) -> Reading:
    """One measurement of one edge, at one moment.

    The verdict is the same `is_anomalous(z)` call the anomalies insert
    uses — deliberately the same call and not a second threshold, so a
    reading and an anomaly row can never disagree about the same point.

    A `deviation` of None means the scorer is still warming up
    (`MIN_OBSERVATIONS`), and the verdict is `inconclusive` with a reason
    saying so, not a silently dropped measurement. "I looked and could not
    yet tell" is a different statement from "nothing happened here", and
    §2.6 makes the first one first-class precisely so a reader can tell
    the two apart.

    `measured` carries the deviation and the sample count behind it, not
    the raw value: a z-score is meaningless without knowing how long the
    baseline has been accumulating, and 3.4 sigma off a 31-observation
    baseline is a different claim from 3.4 sigma off a 30,000-observation
    one.
    """
    if deviation is None:
        verdict = Verdict.INCONCLUSIVE
        reason = (
            f"baseline still warming up: {samples} of {MIN_OBSERVATIONS} "
            "observations needed before a deviation means anything"
        )
    else:
        verdict = Verdict.FAIL if is_anomalous(deviation) else Verdict.PASS
        reason = None

    return Reading(
        probe_id=IMPEDANCE_PROBE_ID,
        probe_version=IMPEDANCE_PROBE_VERSION,
        target=target,
        environment=IMPEDANCE_ENVIRONMENT,
        verdict=verdict,
        measured={"metric": metric_name, "deviation": deviation, "samples": samples},
        reason=reason,
        taken_at=taken_at,
        agent_id=IMPEDANCE_AGENT_ID,
        grants_used=(Capability.TELEMETRY_METRICS_READ,),
    )


def _reading_row(reading: Reading) -> dict[str, Any]:
    """One `readings` row, as a plain mapping for a Core insert.

    `id` is generated here rather than left to the column's
    `gen_random_uuid()` default so the insert needs no RETURNING —
    `probe-writer` holds INSERT and not SELECT, and Postgres will not
    return a row from a table the caller cannot read. Same reasoning as
    `api/app/facts/service.py`'s.
    """
    return dict(
        id=uuid4(),
        taken_at=reading.taken_at,
        probe_id=reading.probe_id,
        probe_version=reading.probe_version,
        target=reading.target,
        environment=reading.environment,
        verdict=str(reading.verdict),
        measured=reading.measured,
        expected=None,
        expected_source=None,
        evidence=[],
        reason=reading.reason or None,
        expires_at=None,
        agent_id=reading.agent_id,
        grants_used=[str(grant) for grant in reading.grants_used],
    )


@instrument_job("score_new_metrics")
async def score_new_metrics(ctx: dict) -> dict:
    redis_client: redis.Redis = ctx["anomaly_redis"]
    engine: AsyncEngine = ctx["anomaly_engine"]
    # A second engine, under probe-writer: a reading is the OBSERVED
    # plane, and anomaly-detector has no grant on `readings` by design.
    probe_engine: AsyncEngine = ctx["probe_engine"]

    watermark = await load_watermark(redis_client)

    query = (
        select(
            raw_events.c.id,
            raw_events.c.time,
            raw_events.c.service_name,
            raw_events.c.metric_name,
            raw_events.c.value,
            # Phase 31: needed to attribute a row to a connection. Read
            # for the peer name only -- nothing else in it is looked at,
            # and nothing from it reaches a reading.
            raw_events.c.attributes,
        )
        .where(raw_events.c.event_type == "metric")
        .where(raw_events.c.id > watermark)
        .order_by(raw_events.c.id)
        .limit(BATCH_SIZE)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()

    if not rows:
        return {"scored": 0, "anomalies": 0, "readings": 0}

    monitored_metrics = await _load_monitored_metrics(engine)
    inbound = await _load_inbound_connections(engine)
    known_components = set(monitored_metrics)

    scorers: dict[tuple[str, str], MetricScorer] = {}
    anomaly_rows: list[dict] = []
    #: The most recent impedance reading per (connection subject, metric)
    #: in this batch. See the comment where it is populated.
    latest_impedance: dict[tuple[str, str], Reading] = {}
    max_id = watermark

    for row in rows:
        max_id = max(max_id, row.id)
        if row.metric_name is None or row.value is None:
            continue
        if not _metric_allowed(row.metric_name, monitored_metrics.get(row.service_name, [])):
            continue

        key = (row.service_name, row.metric_name)
        scorer = scorers.get(key)
        if scorer is None:
            scorer = await load_scorer(redis_client, row.service_name, row.metric_name)

        z = scorer.update(row.value)
        scorers[key] = scorer

        # A warm-up row writes no anomaly (there is no score to threshold)
        # but still writes a reading, as `inconclusive`. Skipping it
        # entirely would make "not measurable yet" and "measured, nothing
        # unusual" indistinguishable in the OBSERVED plane.
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

        target = _impedance_target(row.service_name, row.attributes, known_components, inbound)
        if target is not None:
            # One reading per (connection, metric) per batch, not one per
            # row. A reading answers "what is this connection's impedance
            # now", and the scorer's state is cumulative — so 2000 rows of
            # one metric are 2000 restatements of one measurement, not
            # 2000 measurements. Writing them all would put the raw metric
            # event rate into a 90-day hypertable while `anomalies`, which
            # only gains a row when something is actually wrong, stays
            # small. Keyed by insertion order, so the last row scored wins
            # and the reading carries the most recent deviation.
            #
            # The cost, and it is real: during a catch-up batch spanning a
            # long window, an intermediate spike is not preserved as a
            # reading. It is still preserved as an `anomalies` row, which
            # is the record that exists for exactly that purpose.
            latest_impedance[(target, row.metric_name)] = _impedance_reading(
                target=target,
                metric_name=row.metric_name,
                deviation=z,
                samples=scorer.n,
                taken_at=row.time,
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

    # Before the watermark advances too, and for the same reason: a
    # failed readings insert leaves the batch to be reprocessed from
    # unchanged state. Its own transaction, under its own role, because
    # the two writes are to different planes and neither should be able
    # to roll the other back.
    reading_rows = [_reading_row(reading) for reading in latest_impedance.values()]
    if reading_rows:
        async with probe_engine.begin() as conn:
            await conn.execute(insert(readings), reading_rows)

    await save_progress(redis_client, scorers, max_id)

    logger.info(
        "scored %d metric events, flagged %d anomalies, wrote %d readings",
        len(rows),
        len(anomaly_rows),
        len(reading_rows),
    )
    return {
        "scored": len(rows),
        "anomalies": len(anomaly_rows),
        "readings": len(reading_rows),
    }
