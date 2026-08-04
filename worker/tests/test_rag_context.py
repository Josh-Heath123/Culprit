"""Unit tests for the pure half of app/rag/context.py.

build_incident_context does real DB I/O and isn't unit-tested here (same
convention as app/anomaly/job.py and app/correlation/job.py — the I/O
wiring isn't unit-tested, only the pure logic it calls). render_embedding_text
takes a plain IncidentContext and has no I/O, so it's tested directly.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.rag.context import (
    MAX_LOG_MESSAGE_CHARS_FOR_EMBEDDING,
    AnomalySummary,
    IncidentContext,
    render_embedding_text,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _context(
    services: list[str] | None = None,
    anomaly_summaries: list[AnomalySummary] | None = None,
    log_messages: list[str] | None = None,
) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid4(),
        opened_at=T0,
        last_anomaly_at=T0,
        services=services if services is not None else ["order-service", "inventory-service"],
        anomaly_summaries=(
            anomaly_summaries
            if anomaly_summaries is not None
            else [AnomalySummary("inventory-service", "demo.http.server.duration", 4.2, T0)]
        ),
        log_messages=(
            log_messages if log_messages is not None else ["reserved 3 of sku-1 for order abc"]
        ),
    )


def test_render_embedding_text_includes_services_and_metrics() -> None:
    text = render_embedding_text(_context())
    assert "order-service" in text
    assert "inventory-service" in text
    assert "demo.http.server.duration" in text
    assert "4.20" in text


def test_render_embedding_text_includes_log_messages() -> None:
    text = render_embedding_text(_context())
    assert "reserved 3 of sku-1 for order abc" in text


def test_render_embedding_text_truncates_long_log_messages() -> None:
    long_message = "x" * 1000
    text = render_embedding_text(_context(log_messages=[long_message]))
    # The full 1000-char message must never appear verbatim.
    assert long_message not in text
    assert "x" * MAX_LOG_MESSAGE_CHARS_FOR_EMBEDDING in text


def test_render_embedding_text_handles_no_logs() -> None:
    text = render_embedding_text(_context(log_messages=[]))
    assert "order-service" in text
