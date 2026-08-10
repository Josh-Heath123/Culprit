"""Unit tests for the pure ORM-row -> API-response transforms
(app/incidents/transforms.py). No database — ORM models are instantiated
in-memory (never flushed to a session), same convention as the worker's
pure-logic tests (e.g. worker/tests/test_correlation_graph.py).
"""

import uuid
from datetime import UTC, datetime

from app.db.models import AiChangeRecord, Anomaly, IncidentCandidate
from app.incidents.transforms import (
    ai_change_record_summary,
    anomaly_out,
    incident_detail,
    incident_summary,
    root_cause_status,
    services_for,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _anomaly(service_name: str, metric_name: str = "demo.http.server.duration") -> Anomaly:
    return Anomaly(
        id=uuid.uuid4(),
        service_name=service_name,
        metric_name=metric_name,
        score=4.2,
        threshold=3.0,
        detected_at=T0,
    )


def _incident(**overrides) -> IncidentCandidate:
    defaults = dict(
        id=uuid.uuid4(),
        status="open",
        opened_at=T0,
        closed_at=None,
        last_anomaly_at=T0,
        root_cause_hypothesis=None,
        root_cause_confidence=None,
        root_cause_confidence_reason=None,
        root_cause_evidence=None,
        root_cause_generated_at=None,
    )
    defaults.update(overrides)
    incident = IncidentCandidate(**defaults)
    incident.anomalies = overrides.get("anomalies", [])
    return incident


def test_root_cause_status_pending_when_never_generated() -> None:
    assert root_cause_status(_incident()) == "pending"


def test_root_cause_status_ready_once_generated() -> None:
    incident = _incident(root_cause_generated_at=T0)
    assert root_cause_status(incident) == "ready"


def test_services_for_deduplicates_and_sorts() -> None:
    anomalies = [
        _anomaly("order-service"),
        _anomaly("inventory-service"),
        _anomaly("order-service"),
    ]
    assert services_for(anomalies) == ["inventory-service", "order-service"]


def test_services_for_empty() -> None:
    assert services_for([]) == []


def test_anomaly_out_maps_all_fields() -> None:
    anomaly = _anomaly("payments-service", "demo.http.server.errors")
    out = anomaly_out(anomaly)
    assert out.service_name == "payments-service"
    assert out.metric_name == "demo.http.server.errors"
    assert out.score == 4.2
    assert out.detected_at == T0


def test_incident_summary_includes_services_and_anomalies() -> None:
    anomalies = [_anomaly("order-service"), _anomaly("inventory-service")]
    incident = _incident(anomalies=anomalies)
    summary = incident_summary(incident)
    assert summary.services == ["inventory-service", "order-service"]
    assert len(summary.anomalies) == 2
    assert summary.root_cause_status == "pending"


def test_incident_summary_excludes_detail_only_fields() -> None:
    """IncidentSummary has no root_cause_evidence/confidence_reason field at
    all — this is what keeps the list payload lighter than the detail one."""
    summary = incident_summary(_incident())
    assert not hasattr(summary, "root_cause_evidence")
    assert not hasattr(summary, "root_cause_confidence_reason")


def test_incident_detail_includes_cited_evidence() -> None:
    incident = _incident(
        root_cause_generated_at=T0,
        root_cause_hypothesis="inventory-service's slow lock caused this.",
        root_cause_confidence="High",
        root_cause_confidence_reason="Matches a near-identical past incident.",
        root_cause_evidence=[
            {
                "postmortem_id": str(uuid.uuid4()),
                "postmortem_title": "Inventory-service latency spike",
                "passage": "a synchronous stock-lookup path...",
            }
        ],
    )
    detail = incident_detail(incident, [])
    assert detail.root_cause_status == "ready"
    assert detail.root_cause_confidence == "High"
    assert len(detail.root_cause_evidence) == 1
    assert detail.root_cause_evidence[0].postmortem_title == "Inventory-service latency spike"


def test_incident_detail_handles_no_evidence_yet() -> None:
    detail = incident_detail(_incident(), [])
    assert detail.root_cause_evidence == []
    assert detail.root_cause_status == "pending"


def test_incident_detail_includes_linked_ai_change_records() -> None:
    record = AiChangeRecord(
        id=uuid.uuid4(),
        commit_sha="a" * 40,
        summary="Fix the retry loop",
        files_changed=["demo-services/order_service/main.py"],
        committed_at=T0,
    )
    detail = incident_detail(_incident(), [record])
    assert len(detail.linked_ai_change_records) == 1
    linked = detail.linked_ai_change_records[0]
    assert linked.commit_sha == "a" * 40
    assert linked.summary == "Fix the retry loop"


def test_incident_detail_handles_no_linked_records() -> None:
    detail = incident_detail(_incident(), [])
    assert detail.linked_ai_change_records == []


def test_ai_change_record_summary_maps_fields() -> None:
    record = AiChangeRecord(
        id=uuid.uuid4(),
        commit_sha="b" * 40,
        summary="Add a missing index",
        files_changed=[],
        committed_at=T0,
    )
    summary = ai_change_record_summary(record)
    assert summary.commit_sha == "b" * 40
    assert summary.summary == "Add a missing index"
    assert summary.committed_at == T0
