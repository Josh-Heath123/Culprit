"""Redis persistence for anomaly-scorer state.

Keeps the pure scoring math (scorer.py) free of I/O. This is the only
module in app.anomaly that talks to Redis, and it knows nothing about
River's internals beyond pickling/unpickling a whole MetricScorer.

Uses its own Redis client in bytes mode (no decode_responses) — pickled
data isn't valid UTF-8, so it can't share a decode_responses=True client
with Phase 3's stream-consumer code.
"""

import pickle

import redis.asyncio as redis

from app.anomaly.scorer import MetricScorer

_SCORER_KEY_PREFIX = b"anomaly:scorer"
_WATERMARK_KEY = b"anomaly:watermark:raw_events_id"


def _scorer_key(service_name: str, metric_name: str) -> bytes:
    return f"{_SCORER_KEY_PREFIX.decode()}:{service_name}:{metric_name}".encode()


async def load_scorer(client: redis.Redis, service_name: str, metric_name: str) -> MetricScorer:
    raw = await client.get(_scorer_key(service_name, metric_name))
    if raw is None:
        return MetricScorer()
    scorer = pickle.loads(raw)
    if not isinstance(scorer, MetricScorer):
        raise TypeError(f"expected MetricScorer, got {type(scorer)!r}")
    return scorer


async def load_watermark(client: redis.Redis) -> int:
    raw = await client.get(_WATERMARK_KEY)
    return int(raw) if raw is not None else 0


async def save_progress(
    client: redis.Redis, scorers: dict[tuple[str, str], MetricScorer], watermark: int
) -> None:
    """Persist updated scorer state and the new watermark together, in one
    MULTI/EXEC transaction (redis-py's pipeline default).

    These two updates must not be split across separate round trips: if
    the scorer state were saved but the watermark write then failed (or
    vice versa), the next run would either replay already-counted values
    into the scorer a second time — corrupting the EWMA/EWVar baseline,
    not just duplicating a row — or advance past events whose scores were
    never persisted.
    """
    pipe = client.pipeline(transaction=True)
    for (service_name, metric_name), scorer in scorers.items():
        pipe.set(_scorer_key(service_name, metric_name), pickle.dumps(scorer))
    pipe.set(_WATERMARK_KEY, str(watermark).encode())
    await pipe.execute()
