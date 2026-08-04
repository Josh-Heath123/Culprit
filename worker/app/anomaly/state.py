"""Redis persistence for anomaly-scorer state.

Keeps the pure scoring math (scorer.py) free of I/O. This is the only
module in app.anomaly that talks to Redis.

Serializes MetricScorer via to_dict()/from_dict() (plain floats/int) as
JSON, not pickle.loads/dumps — this used to pickle the whole scorer,
including river.stats objects with no public deserialization contract,
which meant an attacker who could write to this Redis key could get
arbitrary code execution via a crafted pickle on the next load_scorer()
call. Redis isn't network-exposed in this deployment today, so that was
a latent risk rather than an active one, but pickle.loads on anything
network-adjacent is worth removing on principle rather than relying on
network topology to stay this way forever. See scorer.py's MetricScorer
docstring for how to_dict()/from_dict() reconstructs state exactly
without pickle.

Uses its own Redis client (see app/main.py's ctx["anomaly_redis"]),
separate from the stream-consumer's — not because JSON needs bytes mode
(it doesn't; JSON is valid UTF-8, unlike the pickle blobs this used to
store), just because there's no reason to share a connection across two
otherwise-unrelated jobs.
"""

import json

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
    return MetricScorer.from_dict(json.loads(raw))


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
        pipe.set(_scorer_key(service_name, metric_name), json.dumps(scorer.to_dict()))
    pipe.set(_WATERMARK_KEY, str(watermark).encode())
    await pipe.execute()
