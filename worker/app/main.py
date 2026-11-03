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

from app.env import require_env  # noqa: E402
from app.observability import configure_observability  # noqa: E402

configure_observability("culprit-worker")

from app.anomaly.job import score_new_metrics  # noqa: E402
from app.consumer import drain_edges, drain_streams, ensure_consumer_groups  # noqa: E402
from app.correlation.job import correlate_recent_anomalies  # noqa: E402
from app.memory.link_job import link_recent_changes  # noqa: E402
from app.rag.embed_job import (  # noqa: E402
    embed_ai_change_record,
    embed_architecture_decision,
    embed_postmortem,
)
from app.rag.job import generate_root_cause_narrative  # noqa: E402

# One URL per least-privilege role, all required (Phase 26,
# docs/DIAGNOSTIC_PLAN.md). These used to default to committed
# `<role>-dev-password` connection strings, which turned "you forgot a
# variable" from a startup crash into a confusing connection failure
# under the wrong identity later. See app/env.py.
DATABASE_URL = require_env("DATABASE_URL", hint="ingestion-writer; see worker/.env.example")
ANOMALY_DATABASE_URL = require_env(
    "ANOMALY_DATABASE_URL", hint="anomaly-detector; see worker/.env.example"
)
CORRELATION_DATABASE_URL = require_env(
    "CORRELATION_DATABASE_URL", hint="correlation-engine; see worker/.env.example"
)
ROOT_CAUSE_DATABASE_URL = require_env(
    "ROOT_CAUSE_DATABASE_URL", hint="root-cause-writer; see worker/.env.example"
)
# Phase 31: the OBSERVED plane. anomaly-detector has INSERT on
# `anomalies` and deliberately nothing on `readings`, so the impedance
# readings app/anomaly/job.py emits go through their own role.
PROBE_WRITER_DATABASE_URL = require_env(
    "PROBE_WRITER_DATABASE_URL", hint="probe-writer; see worker/.env.example"
)

#: Still defaulted, deliberately: an unreachable Redis is a loud,
#: immediate connection error at the point of use, not a silent
#: connection under the wrong identity. It is a service address, not a
#: credential.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


async def startup(ctx: dict) -> None:
    ctx["redis"] = redis.from_url(REDIS_URL, decode_responses=True)
    ctx["engine"] = create_async_engine(DATABASE_URL)
    await ensure_consumer_groups(ctx["redis"])

    # Separate client (bytes mode — pickled state isn't valid UTF-8) and a
    # separate least-privilege DB role from the stream consumer above.
    ctx["anomaly_redis"] = redis.from_url(REDIS_URL)
    ctx["anomaly_engine"] = create_async_engine(ANOMALY_DATABASE_URL)

    # Used by the same job, for its second output. A separate engine, not
    # a second connection on the one above, because they run as different
    # roles -- the point of the split is that the scoring role cannot
    # write a reading and the probe role cannot read a metric.
    # hide_parameters, as api/app/main.py's probe engine sets it: a failing
    # insert must not log its bound parameters, and a reading's `measured`
    # is JSONB built from telemetry.
    ctx["probe_engine"] = create_async_engine(PROBE_WRITER_DATABASE_URL, hide_parameters=True)

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
    await ctx["probe_engine"].dispose()
    await ctx["correlation_engine"].dispose()
    await ctx["rag_engine"].dispose()
    await ctx["rag_pool"].aclose()


class WorkerSettings:
    functions: ClassVar[list] = [
        generate_root_cause_narrative,
        # Higher max_tries than the Worker-wide default (5): a burst of
        # writes against Voyage's 3 requests/minute free-tier limit needs
        # more headroom than one-off jobs like root-cause generation do,
        # since app/rag/embed_job.py's own backoff can legitimately spend
        # a try every 20-60s under sustained rate limiting
        # (docs/SELF_HOSTED_PLAN.md Phase 18). Same reasoning applies to
        # the Phase 21 (docs/AI_NATIVE_PLAN.md) jobs below — all three
        # share embed_job.py's one rate-limit/retry implementation.
        func(embed_postmortem, max_tries=10),  # pyright: ignore[reportArgumentType]
        func(embed_architecture_decision, max_tries=10),  # pyright: ignore[reportArgumentType]
        func(embed_ai_change_record, max_tries=10),  # pyright: ignore[reportArgumentType]
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
        # Staggered 1s apart so the four jobs don't contend for the same
        # instant every cycle, and so correlation naturally runs after
        # anomaly detection has had a chance to write new anomalies from
        # the same tick. drain_edges has its own consumer group/lock
        # (app/consumer.py), so the 1s offset from drain_streams is purely
        # to spread DB load, not to avoid a real Redis-key collision.
        cron(drain_edges, second=set(range(1, 60, 5))),  # pyright: ignore[reportArgumentType]
        cron(score_new_metrics, second=set(range(2, 60, 5))),  # pyright: ignore[reportArgumentType]
        cron(
            correlate_recent_anomalies,  # pyright: ignore[reportArgumentType]
            second=set(range(4, 60, 5)),
        ),
        # Phase 23 (docs/AI_NATIVE_PLAN.md): offset 3 was the one unused
        # slot in this family — deliberately placed before
        # correlate_recent_anomalies's own offset 4, not after. Running
        # before this cycle's correlation step means an incident created
        # in *this* tick is only picked up on the *next* offset-3 run, a
        # few seconds later — acceptable (see link_job.py's own
        # INCIDENT_RESCAN_WINDOW, generous enough that a one-cycle delay
        # here never causes a real match to be missed).
        cron(link_recent_changes, second=set(range(3, 60, 5))),  # pyright: ignore[reportArgumentType]
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
