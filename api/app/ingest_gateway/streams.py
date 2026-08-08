from collections.abc import Sequence

import redis.asyncio as redis
from pydantic import BaseModel

METRICS_STREAM = "otel-metrics"
LOGS_STREAM = "otel-logs"
#: Phase 19: edge *observations* only (ServiceEdgeObservation), never
#: spans — same volume-reduction reasoning as raw_events never storing
#: full telemetry, applied to traces.
TRACES_STREAM = "otel-traces"


async def push_events[T: BaseModel](client: redis.Redis, stream: str, events: Sequence[T]) -> None:
    """Generic over any pydantic model with the wire shape a consumer on
    the other end validates against — RawEventIn for METRICS_STREAM/
    LOGS_STREAM, ServiceEdgeObservation for TRACES_STREAM (see
    worker/app/consumer.py, which validates each entry the same way
    regardless of which model it is)."""
    if not events:
        return
    pipe = client.pipeline()
    for event in events:
        pipe.xadd(stream, {"data": event.model_dump_json()})
    await pipe.execute()
