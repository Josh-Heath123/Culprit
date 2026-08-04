import redis.asyncio as redis

from app.ingest_gateway.schemas import RawEventIn

METRICS_STREAM = "otel-metrics"
LOGS_STREAM = "otel-logs"


async def push_events(client: redis.Redis, stream: str, events: list[RawEventIn]) -> None:
    if not events:
        return
    pipe = client.pipeline()
    for event in events:
        pipe.xadd(stream, {"data": event.model_dump_json()})
    await pipe.execute()
