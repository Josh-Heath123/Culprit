import logging
import os
from typing import ClassVar

import redis.asyncio as redis
from arq import cron, func
from arq.connections import RedisSettings
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from app.env import require_env  # noqa: E402
from app.observability import configure_observability  # noqa: E402

configure_observability("culprit-worker")

from app.anomaly.job import score_new_metrics  # noqa: E402
from app.consumer import drain_edges, drain_streams, ensure_consumer_groups  # noqa: E402
from app.memory.link_job import link_recent_changes  # noqa: E402
from app.narrate import providers as narrate_providers  # noqa: E402
from app.narrate.config import from_env as narrator_config_from_env  # noqa: E402
from app.narrate.job import narrate_investigations  # noqa: E402
from app.rag.embed_job import (  # noqa: E402
    embed_ai_change_record,
    embed_architecture_decision,
    embed_postmortem,
)

# One URL per least-privilege role, all required (Phase 26,
# docs/DIAGNOSTIC_PLAN.md). These used to default to committed
# `<role>-dev-password` connection strings, which turned "you forgot a
# variable" from a startup crash into a confusing connection failure
# under the wrong identity later. See app/env.py.
DATABASE_URL = require_env("DATABASE_URL", hint="ingestion-writer; see worker/.env.example")
ANOMALY_DATABASE_URL = require_env(
    "ANOMALY_DATABASE_URL", hint="anomaly-detector; see worker/.env.example"
)
# Phase 32 part 2 removed the correlation engine and the incident narrative
# job (docs/DIAGNOSTIC_PLAN.md, D5); the incident tables are read-only
# history. The two roles those jobs ran as are still used, by jobs that stay:
# app/memory/link_job.py runs as correlation-engine, and app/rag/embed_job.py
# (postmortems and the rest of engineering memory) as root-cause-writer. The
# migration took away only their incident-table writes.
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

# Phase 35 part 2: the narrator, as its own role -- SELECT on the
# investigation tables and its narrations, INSERT on narrations. Required
# even with narration off, so turning it on is a setting, not a credential.
NARRATOR_DATABASE_URL = require_env(
    "NARRATOR_DATABASE_URL", hint="narrator; see worker/.env.example"
)
# LLM_PROVIDER, NARRATOR_MODEL and the provider's key or address: read and
# checked now, so a half-set provider stops the worker instead of failing
# every narration later (app/narrate/config.py).
NARRATOR_CONFIG = narrator_config_from_env()

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

    # app/memory/link_job.py's engine; the key keeps its old name because
    # the role does.
    ctx["correlation_engine"] = create_async_engine(CORRELATION_DATABASE_URL)
    # app/rag/embed_job.py's engine, as root-cause-writer.
    ctx["rag_engine"] = create_async_engine(ROOT_CAUSE_DATABASE_URL)
    # app/narrate/job.py's engine, as narrator. With LLM_PROVIDER=none the
    # provider is None and the job returns before touching it.
    ctx["narrator_engine"] = create_async_engine(NARRATOR_DATABASE_URL, hide_parameters=True)
    ctx["narrator_config"] = NARRATOR_CONFIG
    ctx["narrator_provider"] = narrate_providers.build(NARRATOR_CONFIG)


async def shutdown(ctx: dict) -> None:
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()
    await ctx["anomaly_redis"].aclose()
    await ctx["anomaly_engine"].dispose()
    await ctx["probe_engine"].dispose()
    await ctx["correlation_engine"].dispose()
    await ctx["rag_engine"].dispose()
    await ctx["narrator_engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list] = [
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
        # Staggered 1s apart so the jobs don't contend for the same instant
        # every cycle. drain_edges has its own consumer group/lock
        # (app/consumer.py), so the 1s offset from drain_streams is purely
        # to spread DB load, not to avoid a real Redis-key collision.
        cron(drain_edges, second=set(range(1, 60, 5))),  # pyright: ignore[reportArgumentType]
        cron(score_new_metrics, second=set(range(2, 60, 5))),  # pyright: ignore[reportArgumentType]
        # Phase 23 (docs/AI_NATIVE_PLAN.md). Since Phase 32 part 2 nothing
        # creates incidents, so this finds none to link; it is kept because
        # it reads only, and its table is not one of the frozen ones.
        cron(link_recent_changes, second=set(range(3, 60, 5))),  # pyright: ignore[reportArgumentType]
        # Phase 35 part 2: narrate settled investigations. Every 15 seconds;
        # a no-op with LLM_PROVIDER=none.
        cron(narrate_investigations, second={4, 19, 34, 49}),  # pyright: ignore[reportArgumentType]
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
