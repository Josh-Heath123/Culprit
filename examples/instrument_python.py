"""Standalone example: point a Python service's OpenTelemetry metrics at
a running Culprit instance and report one request-duration measurement.

Genuinely standalone — copy this file into your own service and it just
works. It does not import anything from the Culprit repo (unlike
demo-services/shared/otel.py, which imports culprit_shared and is
therefore NOT copyable as-is; see docs/INSTRUMENTATION.md).

Requires:
    pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http

Configure with two env vars (see docs/INSTRUMENTATION.md §5):
    OTEL_EXPORTER_OTLP_ENDPOINT=https://<your-domain>/ingest
    OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20clp_live_your_key_here
"""

import os
import random
import time

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# Must match a service name you've already registered with Culprit
# (Settings -> Services, or POST /model/components) byte-for-byte — see
# docs/INSTRUMENTATION.md §2 for what happens if it doesn't.
SERVICE_NAME = "your-service-name-here"

# {base}/v1/metrics — OTEL_EXPORTER_OTLP_ENDPOINT is the {base} from
# docs/INSTRUMENTATION.md §2 (e.g. https://<your-domain>/ingest), and
# the exporter appends /v1/metrics itself.
otlp_endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/")

resource = Resource.create({"service.name": SERVICE_NAME})
# Authorization comes from OTEL_EXPORTER_OTLP_HEADERS automatically —
# OTLPMetricExporter reads that env var itself, no need to pass headers=
# here explicitly.
exporter = OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
# 10s: matches what docs/INSTRUMENTATION.md and the anomaly scorer
# assume a "normal" export cadence looks like. Faster is fine; much
# slower means the scorer sees fewer data points per unit time.
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=10_000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter(SERVICE_NAME)
request_duration = meter.create_histogram(
    "http.server.request.duration",
    unit="ms",
    description="Duration of one handled HTTP request",
)


def handle_one_request() -> None:
    """Stand-in for your actual request handler — replace this with a
    real timing measurement around whatever your service does."""
    start = time.perf_counter()
    time.sleep(random.uniform(0.01, 0.05))  # pretend work
    duration_ms = (time.perf_counter() - start) * 1000
    request_duration.record(duration_ms)


if __name__ == "__main__":
    print(f"Reporting {SERVICE_NAME} metrics to {otlp_endpoint} every 10s. Ctrl+C to stop.")
    try:
        while True:
            handle_one_request()
            time.sleep(1)
    except KeyboardInterrupt:
        provider.shutdown()
