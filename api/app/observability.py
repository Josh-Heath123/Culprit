"""Self-observability setup for the api/ project (Phase 10) — OTel traces
to Tempo, structlog JSON logs to stdout, with the active span's
trace_id/span_id attached to every log entry. That correlation (a log
line and its Tempo trace pointing at the same id) is the actual point of
running both together, not two disconnected features bolted on side by
side.

Shared by both uvicorn processes in this project (app/main.py, the
dashboard API, and app/ingest_gateway/main.py) since they're the same
Python package — not shared with worker/, which is a separate package
with its own worker/app/observability.py following the same pattern
(env-var-driven OTLP endpoint, Resource with service.name set per
caller), same as demo-services/shared/otel.py already established for
the demo services.

Traces + structured logs only — no OTel metrics instrumentation.
infra/docker-compose.yml only runs Tempo + Grafana, no Prometheus/Mimir
to receive metrics, and inert instrumentation with nowhere to send it
isn't worth the code (see docs/IMPLEMENTATION_PLAN.md Phase 10).
"""

import logging
import os

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

_DEFAULT_TRACES_ENDPOINT = "http://localhost:4318"

_configured = False


def _add_trace_context(
    logger: structlog.types.WrappedLogger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor: stamp trace_id/span_id (hex, matching Tempo's
    own display format) onto every log entry made while a span is
    active. No-op when nothing is tracing (e.g. at process startup,
    before any request/job span has opened)."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def configure_observability(service_name: str) -> None:
    """Idempotent — safe to call more than once (e.g. once from a
    module's own top level and once from a test import) without
    double-registering exporters or processors."""
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
