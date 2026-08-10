"""Pure ORM-row -> API-response transforms. No I/O — unit-tested directly
(api/tests/test_incidents_transforms.py) without a database, same
convention as the worker's pure/impure split (e.g. app/anomaly/scorer.py
vs app/anomaly/job.py).
"""

from typing import Literal, cast

from app.db.models import AiChangeRecord, Anomaly, IncidentCandidate
from app.incidents.schemas import (
    AiChangeRecordSummary,
    AnomalyOut,
    CitedEvidenceOut,
    IncidentDetail,
    IncidentSummary,
)

_Status = Literal["open", "investigating", "resolved"]
_Confidence = Literal["High", "Medium", "Low"]


def _status(value: str) -> _Status:
    """SQLAlchemy's Mapped[str] can't carry the ck_incident_candidates_status
    CHECK constraint's domain in Python's type system — this cast documents
    that the DB, not this function, is what actually guarantees the value
    is one of the three literals."""
    return cast(_Status, value)


def _confidence(value: str | None) -> _Confidence | None:
    """Same reasoning as _status, for ck_incident_candidates_root_cause_confidence."""
    return cast(_Confidence | None, value)


def root_cause_status(incident: IncidentCandidate) -> Literal["pending", "ready"]:
    """'ready' once Phase 6 has written a narrative (root_cause_generated_at
    is set), 'pending' beforehand — a freshly-created incident always
    starts pending, and stays that way until the event-driven RAG job
    (enqueued the moment correlation created it) completes."""
    return "ready" if incident.root_cause_generated_at is not None else "pending"


def services_for(anomalies: list[Anomaly]) -> list[str]:
    return sorted({anomaly.service_name for anomaly in anomalies})


def anomaly_out(anomaly: Anomaly) -> AnomalyOut:
    return AnomalyOut(
        id=anomaly.id,
        service_name=anomaly.service_name,
        metric_name=anomaly.metric_name,
        score=anomaly.score,
        detected_at=anomaly.detected_at,
    )


def incident_summary(incident: IncidentCandidate) -> IncidentSummary:
    anomalies = list(incident.anomalies)
    return IncidentSummary(
        id=incident.id,
        status=_status(incident.status),
        opened_at=incident.opened_at,
        closed_at=incident.closed_at,
        last_anomaly_at=incident.last_anomaly_at,
        services=services_for(anomalies),
        anomalies=[anomaly_out(a) for a in anomalies],
        root_cause_status=root_cause_status(incident),
        root_cause_hypothesis=incident.root_cause_hypothesis,
        root_cause_confidence=_confidence(incident.root_cause_confidence),
    )


def ai_change_record_summary(record: AiChangeRecord) -> AiChangeRecordSummary:
    return AiChangeRecordSummary(
        id=record.id,
        commit_sha=record.commit_sha,
        summary=record.summary,
        committed_at=record.committed_at,
    )


def incident_detail(
    incident: IncidentCandidate, linked_records: list[AiChangeRecord]
) -> IncidentDetail:
    anomalies = list(incident.anomalies)
    evidence_rows = incident.root_cause_evidence or []
    return IncidentDetail(
        id=incident.id,
        status=_status(incident.status),
        opened_at=incident.opened_at,
        closed_at=incident.closed_at,
        last_anomaly_at=incident.last_anomaly_at,
        services=services_for(anomalies),
        anomalies=[anomaly_out(a) for a in anomalies],
        root_cause_status=root_cause_status(incident),
        root_cause_hypothesis=incident.root_cause_hypothesis,
        root_cause_confidence=_confidence(incident.root_cause_confidence),
        root_cause_confidence_reason=incident.root_cause_confidence_reason,
        root_cause_evidence=[CitedEvidenceOut(**row) for row in evidence_rows],
        root_cause_generated_at=incident.root_cause_generated_at,
        linked_ai_change_records=[ai_change_record_summary(r) for r in linked_records],
    )
