"""Decode real OTLP/HTTP protobuf payloads into raw_events rows.

Uses the generated opentelemetry-proto message classes to parse the wire
format — no hand-rolled protobuf parsing. Traces are explicitly out of
scope here (Phase 3 scope correction); only metrics and logs are decoded,
matching raw_events.event_type (metric|log) from the Phase 1 schema.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

from app.ingest_gateway.schemas import RawEventIn


def _any_value_to_python(value: AnyValue) -> object:
    kind = value.WhichOneof("value")
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "array_value":
        return [_any_value_to_python(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _any_value_to_python(kv.value) for kv in value.kvlist_value.values}
    return None


def _attributes_to_dict(attributes: Iterable[KeyValue]) -> dict:
    return {kv.key: _any_value_to_python(kv.value) for kv in attributes}


def _nanos_to_datetime(time_unix_nano: int) -> datetime:
    return datetime.fromtimestamp(time_unix_nano / 1e9, tz=UTC)


def decode_metrics_request(body: bytes, service_name: str) -> list[RawEventIn]:
    """service_name is the authenticated caller's identity, never read from
    the payload's own resource attributes — that's the multi-tenant
    boundary this phase is actually about."""
    request = ExportMetricsServiceRequest()
    request.ParseFromString(body)

    events: list[RawEventIn] = []
    for resource_metrics in request.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                kind = metric.WhichOneof("data")
                if kind in ("sum", "gauge"):
                    data_points = getattr(metric, kind).data_points
                    for point in data_points:
                        is_double = point.WhichOneof("value") == "as_double"
                        value = point.as_double if is_double else point.as_int
                        events.append(
                            RawEventIn(
                                time=_nanos_to_datetime(point.time_unix_nano),
                                service_name=service_name,
                                event_type="metric",
                                metric_name=metric.name,
                                value=float(value),
                                attributes=_attributes_to_dict(point.attributes),
                            )
                        )
                elif kind == "histogram":
                    for point in metric.histogram.data_points:
                        mean = (point.sum / point.count) if point.count else 0.0
                        attrs = _attributes_to_dict(point.attributes)
                        attrs["otel.count"] = point.count
                        attrs["otel.sum"] = point.sum
                        events.append(
                            RawEventIn(
                                time=_nanos_to_datetime(point.time_unix_nano),
                                service_name=service_name,
                                event_type="metric",
                                metric_name=metric.name,
                                value=mean,
                                attributes=attrs,
                            )
                        )
                # exponential_histogram/summary: not emitted by the demo
                # services' instrumentation, so intentionally unhandled.
    return events


def decode_logs_request(body: bytes, service_name: str) -> list[RawEventIn]:
    request = ExportLogsServiceRequest()
    request.ParseFromString(body)

    events: list[RawEventIn] = []
    for resource_logs in request.resource_logs:
        for scope_logs in resource_logs.scope_logs:
            for record in scope_logs.log_records:
                attrs = _attributes_to_dict(record.attributes)
                if record.severity_text:
                    attrs["severity"] = record.severity_text
                if record.trace_id:
                    attrs["trace_id"] = record.trace_id.hex()
                if record.span_id:
                    attrs["span_id"] = record.span_id.hex()
                body_value = _any_value_to_python(record.body)
                event_time = record.time_unix_nano or record.observed_time_unix_nano
                events.append(
                    RawEventIn(
                        time=_nanos_to_datetime(event_time),
                        service_name=service_name,
                        event_type="log",
                        message=str(body_value) if body_value is not None else None,
                        attributes=attrs,
                    )
                )
    return events
