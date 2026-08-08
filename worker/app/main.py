import logging
import os
from typing import ClassVar

import redis.asyncio as redis
from arq import cron, func
from arq.connections import RedisSettings, create_pool
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from app.observability import configure_observability  # noqa: E402

configure_observability("culprit-worker")

from app.anomaly.job import score_new_metrics  # noqa: E402
from app.consumer import drain_streams, ensure_consumer_groups  # noqa: E402
from app.correlation.job import correlate_recent_anomalies  # noqa: E402
from app.rag.embed_job import embed_postmortem  # noqa: E402
from app.rag.job import generate_root_cause_narrative  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://ingestion-writer:ingestion-writer-dev-password@localhost:5432/signalstack",
)
ANOMALY_DATABASE_URL = os.environ.get(
    "ANOMALY_DATABASE_URL",
    "postgresql+asyncpg://anomaly-detector:anomaly-detector-dev-password@localhost:5432/signalstack",
)
CORRELATION_DATABASE_URL = os.environ.get(
    "CORRELATION_DATABASE_URL",
    "postgresql+asyncpg://correlation-engine:correlation-engine-dev-password@localhost:5432/signalstack",
)
ROOT_CAUSE_DATABASE_URL = os.environ.get(
    "ROOT_CAUSE_DATABASE_URL",
    "postgresql+asyncpg://root-cause-writer:root-cause-writer-dev-password@localhost:5432/signalstack",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


async def startup(ctx: dict) -> None:
    ctx["redis"] = redis.from_url(REDIS_URL, decode_responses=True)
    ctx["engine"] = create_async_engine(DATABASE_URL)
    await ensure_consumer_groups(ctx["redis"])

    # Separate client (bytes mode — pickled state isn't valid UTF-8) and a
    # separate least-privilege DB role from the stream consumer above.
    ctx["anomaly_redis"] = redis.from_url(REDIS_URL)
    ctx["anomaly_engine"] = create_async_engine(ANOMALY_DATABASE_URL)

    # Correlation needs no Redis state of its own — it re-derives
    # everything from Postgres each run (anomalies + what's already
    # attached), so a fresh run is naturally idempotent.
    ctx["correlation_engine"] = create_async_engine(CORRELATION_DATABASE_URL)

    # Phase 6: least-privilege engine for the root-cause job, plus a
    # dedicated ArqRedis pool so app.correlation.job can enqueue that job
    # by name the moment it creates a new incident. Arq's own pool would
    # normally live at ctx["redis"], but that key is already claimed above
    # by a plain redis-py client for the stream consumer's XREADGROUP
    # calls — a separate pool here avoids overloading that key with two
    # different client types.
    ctx["rag_engine"] = create_async_engine(ROOT_CAUSE_DATABASE_URL)
    ctx["rag_pool"] = await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def shutdown(ctx: dict) -> None:
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()
    await ctx["anomaly_redis"].aclose()
    await ctx["anomaly_engine"].dispose()
    await ctx["correlation_engine"].dispose()
    await ctx["rag_engine"].dispose()
    await ctx["rag_pool"].aclose()


class WorkerSettings:
    functions: ClassVar[list] = [
        generate_root_cause_narrative,
        # Higher max_tries than the Worker-wide default (5): a burst of
        # postmortem writes against Voyage's 3 requests/minute free-tier
        # limit needs more headroom than one-off jobs like root-cause
        # generation do, since app/rag/embed_job.py's own backoff can
        # legitimately spend a try every 20-60s under sustained rate
        # limiting (docs/SELF_HOSTED_PLAN.md Phase 18).
        func(embed_postmortem, max_tries=10),  # pyright: ignore[reportArgumentType]
    ]
    cron_jobs: ClassVar[list] = [
        # app.observability.instrument_job wraps each of these in a plain
        # Callable[...] (for the generic ParamSpec/TypeVar signature),
        # which structurally drops the bare-function attributes (e.g.
        # __qualname__) arq's WorkerCoroutine Protocol checks for — a
        # static-typing artifact only; every wrapped function still has
        # __qualname__ at runtime (functools.wraps copies it) and is a
        # real async callable arq can run.
        cron(drain_streams, second=set(range(0, 60, 5))),  # pyright: ignore[reportArgumentType]
        # Staggered 2s apart so the three jobs don't contend for the same
        # instant every cycle, and so correlation naturally runs after
        # anomaly detection has had a chance to write new anomalies from
        # the same tick.
        cron(score_new_metrics, second=set(range(2, 60, 5))),  # pyright: ignore[reportArgumentType]
        cron(
            correlate_recent_anomalies,  # pyright: ignore[reportArgumentType]
            second=set(range(4, 60, 5)),
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
