"""Decode real OTLP/HTTP protobuf payloads.

Uses the generated opentelemetry-proto message classes to parse the wire
format — no hand-rolled protobuf parsing. Metrics and logs decode into
raw_events rows, matching raw_events.event_type (metric|log) from the
Phase 1 schema. Traces (Phase 19) decode into something structurally
different — (from_service, to_service) edge observations, never
raw_events rows and never full spans — see decode_traces_request's own
docstring for why.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

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


def _resolve_peer(attributes: dict) -> str | None:
    """Phase 19, Option A's peer-resolution order (docs/SELF_HOSTED_PLAN.md):
    `peer.service` first — a client span that sets it names its target's
    logical service identity directly, the reliable case. Falling back to
    `server.address`'s host (port stripped) is a best-effort guess that
    only resolves correctly when a hostname happens to already match a
    registered service's name; a real hostname→service alias map is a
    known, deliberately unbuilt mitigation for that gap (the Phase 19
    section names it as future work, not part of this phase). Returns
    None — no edge recorded — when neither attribute is present, rather
    than guessing further.
    """
    peer_service = attributes.get("peer.service")
    if isinstance(peer_service, str) and peer_service:
        return peer_service

    server_address = attributes.get("server.address")
    if isinstance(server_address, str) and server_address:
        return server_address.split(":", 1)[0]

    return None


def decode_traces_request(body: bytes, service_name: str) -> list[tuple[str, str]]:
    """Emits edge *observations*, never spans — a list of
    (from_service, to_service) pairs, nothing else. This is what keeps
    the "don't store high-volume raw telemetry" rule intact: the volume
    reduction to two strings per edge happens here, at decode time,
    before anything is queued — no span ever reaches Redis or Postgres.

    `from_service` is always `service_name`, the authenticated caller's
    identity — never read from the payload's own resource attributes.
    Same multi-tenant boundary decode_metrics_request/decode_logs_request
    already enforce: a caller can report what it observed itself calling,
    never claim to speak for a different service.

    Only CLIENT-kind spans carry a resolvable peer at all; every other
    span kind (INTERNAL, SERVER, PRODUCER, CONSUMER) is skipped, as is
    any CLIENT span whose peer can't be resolved (_resolve_peer) or whose
    peer resolves to the caller's own name (not a real cross-service
    edge).
    """
    request = ExportTraceServiceRequest()
    request.ParseFromString(body)

    edges: list[tuple[str, str]] = []
    for resource_spans in request.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                if span.kind != Span.SpanKind.SPAN_KIND_CLIENT:
                    continue
                peer = _resolve_peer(_attributes_to_dict(span.attributes))
                if peer is None or peer == service_name:
                    continue
                edges.append((service_name, peer))
    return edges
