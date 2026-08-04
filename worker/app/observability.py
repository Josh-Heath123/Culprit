"""Self-observability setup for the worker/ project (Phase 10) — OTel
traces to Tempo, structlog JSON logs to stdout, with the active span's
trace_id/span_id attached to every log entry. That correlation (a log
line and its Tempo trace pointing at the same id) is the actual point of
running both together, not two disconnected features bolted on side by
side.

A separate module from api/app/observability.py — api/ and worker/ are
separate Python packages, per CLAUDE.md's "no shared internals" rule —
but follows the exact same pattern (env-var-driven OTLP endpoint,
Resource with service.name set per caller), matching
demo-services/shared/otel.py's precedent too.

Traces + structured logs only — no OTel metrics instrumentation.
infra/docker-compose.yml only runs Tempo + Grafana, no Prometheus/Mimir
to receive metrics, and inert instrumentation with nowhere to send it
isn't worth the code (see docs/IMPLEMENTATION_PLAN.md Phase 10).

instrument_job() is this module's other export: a decorator that gives
every scheduled arq job (app/consumer.py, app/anomaly/job.py,
app/correlation/job.py, app/rag/job.py) a span and a structured
duration/outcome/item-count log entry without changing any of those
modules' own logic — this phase wraps existing behavior, it doesn't
change what anything does.
"""

import functools
import logging
import os
import time
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Status, StatusCode

_DEFAULT_TRACES_ENDPOINT = "http://localhost:4318"

_configured = False


def _add_trace_context(
    logger: structlog.types.WrappedLogger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor: stamp trace_id/span_id (hex, matching Tempo's
    own display format) onto every log entry made while a span is
    active. No-op when nothing is tracing (e.g. at process startup,
    before any job span has opened)."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def configure_observability(service_name: str) -> None:
    """Idempotent — safe to call more than once without double-
    registering exporters or processors."""
    global _configured
    if _configured:
        return
    _configured = True

    resource = Resource.create({"service.name": service_name})

    traces_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", _DEFAULT_TRACES_ENDPOINT)
    tracer_provider = TracerProvider(resource=resource)
    if traces_endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{traces_endpoint.rstrip('/')}/v1/traces")
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_trace_context,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_tracer = trace.get_tracer("culprit.worker")
_job_logger = structlog.get_logger("worker.job")

P = ParamSpec("P")
R = TypeVar("R", bound=dict[str, Any] | None)
JobFunc = Callable[P, Coroutine[Any, Any, R]]


def instrument_job(job_name: str) -> Callable[[JobFunc], JobFunc]:
    """Wraps an arq job function (`async def job(ctx, *args) -> dict`)
    with a span and a structured log line reporting duration, outcome,
    and whatever item counts the job's own return value already carries
    (e.g. correlate_recent_anomalies's {"created": ..., "extended": ...}).
    On an unhandled exception, logs outcome="failure" and re-raises
    unchanged — arq's own retry/failure handling isn't altered.
    """

    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            with _tracer.start_as_current_span(job_name) as span:
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    span.set_status(Status(StatusCode.ERROR))
                    span.record_exception(exc)
                    _job_logger.error(
                        job_name,
                        outcome="failure",
                        duration_ms=round(duration_ms, 2),
                        error=str(exc),
                    )
                    raise
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("job.duration_ms", duration_ms)
                _job_logger.info(
                    job_name,
                    outcome="success",
                    duration_ms=round(duration_ms, 2),
                    **(result or {}),
                )
                return result

        return wrapper

    return decorator
