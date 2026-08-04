import logging
import os

from culprit_shared.services import SERVICE_API_KEY_ENV_VARS
from dotenv import load_dotenv
from opentelemetry import _logs as logs_api
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    ConsoleLogExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

load_dotenv()

# Ingest-gateway (Phase 3) only accepts metrics and logs, matching
# raw_events.event_type — traces stay console-only by default (or point
# OTEL_EXPORTER_OTLP_TRACES_ENDPOINT at infra/docker-compose.yml's Tempo
# for local viewing; that's a separate data stream from SignalStack's own
# self-observability in Phase 10).


def _resolve_endpoint(signal: str) -> str | None:
    """Per-signal OTLP endpoint override, falling back to the generic one —
    the standard OTel env var convention, so traces/metrics/logs can point
    at different collectors independently."""
    specific = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT")
    return specific or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")


def _auth_headers(service_name: str) -> dict[str, str] | None:
    env_var = SERVICE_API_KEY_ENV_VARS.get(service_name)
    api_key = os.environ.get(env_var) if env_var else None
    return {"Authorization": f"Bearer {api_key}"} if api_key else None


def configure_otel(service_name: str) -> None:
    """Wire up traces + metrics + logs for one demo service.

    Metrics/logs export OTLP/HTTP to ingest-gateway (Phase 3) with the
    service's own scoped API key attached, when configured; otherwise
    console exporters so telemetry is at least visible locally.
    """
    resource = Resource.create({"service.name": service_name})
    auth_headers = _auth_headers(service_name)

    traces_endpoint = _resolve_endpoint("TRACES")
    tracer_provider = TracerProvider(resource=resource)
    if traces_endpoint:
        span_exporter = OTLPSpanExporter(endpoint=f"{traces_endpoint.rstrip('/')}/v1/traces")
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    export_interval_ms = int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL_MS", "10000"))
    metrics_endpoint = _resolve_endpoint("METRICS")
    metric_exporter = (
        OTLPMetricExporter(
            endpoint=f"{metrics_endpoint.rstrip('/')}/v1/metrics", headers=auth_headers
        )
        if metrics_endpoint
        else ConsoleMetricExporter()
    )
    reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=export_interval_ms
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    logs_endpoint = _resolve_endpoint("LOGS")
    logger_provider = LoggerProvider(resource=resource)
    if logs_endpoint:
        log_exporter = OTLPLogExporter(
            endpoint=f"{logs_endpoint.rstrip('/')}/v1/logs", headers=auth_headers
        )
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    else:
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(ConsoleLogExporter()))
    logs_api.set_logger_provider(logger_provider)

    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger(service_name).addHandler(handler)
    logging.getLogger(service_name).setLevel(logging.INFO)
