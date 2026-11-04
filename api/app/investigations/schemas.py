"""Response shapes for the investigation routes. The request body is
`culprit_model.investigations.Investigation` itself — exactly what
`culprit diagnose --format json` writes."""

from datetime import datetime

from culprit_model.investigations import (
    Diagnosis,
    FaultEdge,
    Hypothesis,
    InvestigationReading,
    Symptom,
)
from pydantic import BaseModel


class InvestigationStored(BaseModel):
    id: str
    readings: int
    fault_edges: int


class InvestigationSummary(BaseModel):
    id: str
    opened_at: datetime
    environment: str
    symptom_subject: str
    #: "reproduced" or "reported" (§2.8, amended).
    attestation: str
    root_subject: str | None
    complete: bool | None


class InvestigationList(BaseModel):
    items: list[InvestigationSummary]
    limit: int
    offset: int


class TreeEdge(FaultEdge):
    """A fault edge with the readings that established it, inline — what
    the view expands an edge to."""

    readings: list[InvestigationReading]


class HypothesisGroups(BaseModel):
    """Grouped so untested and unexplored are never one thing: untested
    were not needed; unexplored were needed and could not be tested."""

    supported: list[Hypothesis]
    ruled_out: list[Hypothesis]
    unexplored: list[Hypothesis]
    untested: list[Hypothesis]


class InvestigationTree(BaseModel):
    id: str
    environment: str
    opened_at: datetime
    symptom: Symptom
    diagnosis: Diagnosis | None
    fault_tree: list[TreeEdge]
    hypotheses: HypothesisGroups
