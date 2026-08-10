from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AnomalyOut(BaseModel):
    id: UUID
    service_name: str
    metric_name: str
    score: float
    detected_at: datetime


class CitedEvidenceOut(BaseModel):
    postmortem_id: str | None
    postmortem_title: str
    passage: str


class AiChangeRecordSummary(BaseModel):
    """A small citation-like shape (Phase 23, docs/AI_NATIVE_PLAN.md) —
    same minimalism as CitedEvidenceOut above, not a full
    AiChangeRecordOut duplicate. `worker/app/memory/link_job.py`'s own
    `link_reason` isn't included here; it describes the (service, file)
    pair that triggered one specific link, not a property of the change
    record itself."""

    id: UUID
    commit_sha: str
    summary: str
    committed_at: datetime


class IncidentSummary(BaseModel):
    """List-item shape (GET /incidents). Includes anomalies and the
    lightweight root-cause fields — the timeline (dense per-service marks
    + cross-service incident bands) and the command palette's client-side
    fuzzy search over hypothesis text both need this to be available on
    already-loaded incidents, per Phase 8's "no new backend endpoint"
    constraint. Confidence reason, full cited evidence, and the
    generated-at timestamp are detail-only (see IncidentDetail below).
    """

    id: UUID
    status: Literal["open", "investigating", "resolved"]
    opened_at: datetime
    closed_at: datetime | None
    last_anomaly_at: datetime
    services: list[str]
    anomalies: list[AnomalyOut]
    root_cause_status: Literal["pending", "ready"]
    root_cause_hypothesis: str | None
    root_cause_confidence: Literal["High", "Medium", "Low"] | None


class IncidentDetail(IncidentSummary):
    """Detail shape (GET /incidents/{id}): everything in the summary plus
    the full root-cause narrative — confidence reason and cited evidence,
    displayed as footnotes per Section 3's voice charter."""

    root_cause_confidence_reason: str | None
    root_cause_evidence: list[CitedEvidenceOut]
    root_cause_generated_at: datetime | None
    #: Phase 23: AI change records worker/app/memory/link_job.py judged
    #: related to this incident. Detail-only, same reasoning as every
    #: other field in this class — the list endpoint doesn't pay for it.
    linked_ai_change_records: list[AiChangeRecordSummary]


class PaginatedIncidents(BaseModel):
    items: list[IncidentSummary]
    limit: int
    offset: int
    total: int
