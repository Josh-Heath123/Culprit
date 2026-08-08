"""Unit tests for decode_traces_request (Phase 19, Option A).

Payloads are built directly with the generated protobuf message classes
and serialized — functionally identical to a captured OTLP payload, just
constructed rather than checked in as a binary fixture, which keeps every
test case readable and independently reviewable (see
docs/SELF_HOSTED_PLAN.md Phase 19's own Tests section: "a recorded
protobuf payload decodes to the expected edges").
"""

from app.ingest_gateway.otlp_decode import decode_traces_request
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span


def _span(*, kind: "Span.SpanKind.ValueType", attributes: dict[str, str] | None = None) -> Span:
    return Span(
        trace_id=b"\x01" * 16,
        span_id=b"\x02" * 8,
        name="test span",
        kind=kind,
        attributes=[
            KeyValue(key=key, value=AnyValue(string_value=value))
            for key, value in (attributes or {}).items()
        ],
    )


def _request_bytes(*resource_spans: ResourceSpans) -> bytes:
    return ExportTraceServiceRequest(resource_spans=list(resource_spans)).SerializeToString()


def _single_scope(*spans: Span) -> ResourceSpans:
    return ResourceSpans(scope_spans=[ScopeSpans(spans=list(spans))])


def test_client_span_with_peer_service_produces_edge() -> None:
    body = _request_bytes(
        _single_scope(
            _span(
                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                attributes={"peer.service": "inventory-service"},
            )
        )
    )
    assert decode_traces_request(body, "order-service") == [("order-service", "inventory-service")]


def test_client_span_falls_back_to_server_address_host_with_port_stripped() -> None:
    body = _request_bytes(
        _single_scope(
            _span(
                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                attributes={"server.address": "inventory-service:8002"},
            )
        )
    )
    assert decode_traces_request(body, "order-service") == [("order-service", "inventory-service")]


def test_peer_service_wins_over_server_address_when_both_present() -> None:
    body = _request_bytes(
        _single_scope(
            _span(
                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                attributes={
                    "peer.service": "inventory-service",
                    "server.address": "some-internal-host:9999",
                },
            )
        )
    )
    assert decode_traces_request(body, "order-service") == [("order-service", "inventory-service")]


def test_client_span_with_no_resolvable_peer_produces_no_edge() -> None:
    body = _request_bytes(_single_scope(_span(kind=Span.SpanKind.SPAN_KIND_CLIENT)))
    assert decode_traces_request(body, "order-service") == []


def test_non_client_span_kinds_produce_no_edges() -> None:
    non_client_kinds = [
        Span.SpanKind.SPAN_KIND_INTERNAL,
        Span.SpanKind.SPAN_KIND_SERVER,
        Span.SpanKind.SPAN_KIND_PRODUCER,
        Span.SpanKind.SPAN_KIND_CONSUMER,
        Span.SpanKind.SPAN_KIND_UNSPECIFIED,
    ]
    spans = [
        _span(kind=kind, attributes={"peer.service": "inventory-service"})
        for kind in non_client_kinds
    ]
    body = _request_bytes(_single_scope(*spans))
    assert decode_traces_request(body, "order-service") == []


def test_self_referential_edge_is_skipped() -> None:
    body = _request_bytes(
        _single_scope(
            _span(kind=Span.SpanKind.SPAN_KIND_CLIENT, attributes={"peer.service": "order-service"})
        )
    )
    assert decode_traces_request(body, "order-service") == []


def test_multiple_client_spans_across_scopes_all_decode() -> None:
    request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                scope_spans=[
                    ScopeSpans(
                        spans=[
                            _span(
                                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                                attributes={"peer.service": "inventory-service"},
                            )
                        ]
                    ),
                    ScopeSpans(
                        spans=[
                            _span(
                                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                                attributes={"peer.service": "payments-service"},
                            )
                        ]
                    ),
                ]
            )
        ]
    )
    edges = decode_traces_request(request.SerializeToString(), "order-service")
    assert set(edges) == {
        ("order-service", "inventory-service"),
        ("order-service", "payments-service"),
    }


def test_from_service_is_always_the_authenticated_caller_not_the_payload() -> None:
    """Same multi-tenant boundary as decode_metrics_request/
    decode_logs_request — the payload never gets to claim an identity for
    the caller; only the authenticated service_name does."""
    body = _request_bytes(
        _single_scope(
            _span(
                kind=Span.SpanKind.SPAN_KIND_CLIENT,
                attributes={"peer.service": "inventory-service"},
            )
        )
    )
    assert decode_traces_request(body, "some-other-caller") == [
        ("some-other-caller", "inventory-service")
    ]
