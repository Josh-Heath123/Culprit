"""Investigation, Hypothesis and FaultEdge — docs/DIAGNOSTIC_PLAN.md §2.8.

An incident is something that happened to you; an investigation is
something you are doing. It holds the symptom it started from, the
hypotheses the model gave it, every reading it took, and the fault tree
those readings established.

The Python half of `cli/internal/model/investigation.go`, held to the Go
side by `shared/tests/investigation_conformance.json`. `culprit diagnose`
writes an investigation as JSON; Phase 32 part 2's `POST /investigations`
reads it with this model, so a rule the binary enforces and this does not
is a rule a hand-edited file walks straight past.

The rule this module exists for: **a fault edge cannot exist without at
least one reading that established it, and every reading it cites must be
one this investigation took.** An edge is a claim; a claim no measurement
established is narrative masquerading as diagnosis.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.readings import Reading
from culprit_model.subjects import SubjectError
from culprit_model.subjects import parse as parse_subject


def _require_subject(value: str, what: str) -> None:
    try:
        parse_subject(value)
    except SubjectError as exc:
        raise ValueError(f"{what} {value!r} is not a subject URI: {exc}") from exc


class Relation(StrEnum):
    #: `from_subject` (what the user saw) is a symptom of `to_subject`.
    SYMPTOM_OF = "symptom_of"
    #: the failure at `from_subject` (downstream) reached `to_subject`.
    PROPAGATES_TO = "propagates_to"
    #: `from_subject` is failing because of `to_subject`.
    CAUSED_BY = "caused_by"


class HypothesisStatus(StrEnum):
    OPEN = "open"
    RULED_OUT = "ruled_out"
    SUPPORTED = "supported"
    #: the walk could not test it — refused, inconclusive, no vantage, or
    #: out of budget. A partial diagnosis is visibly partial.
    UNEXPLORED = "unexplored"


class SymptomKind(StrEnum):
    SUBJECT = "subject"
    ENDPOINT = "endpoint"
    COMPONENT = "component"


class AttestationKind(StrEnum):
    #: the walk reproduced it read-only: a reading on its subject failed.
    REPRODUCED = "reproduced"
    #: known only from the report it came from (a write cannot be replayed).
    REPORTED = "reported"


class Attestation(BaseModel):
    """What establishes that the symptom happened at all (§2.8, amended
    2026-11-04) — separate from the symptom_of edge, which says what ties
    it to its cause. A symptom only reported is never presented as
    reproduced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AttestationKind
    reading: str | None = None
    reported_by: str | None = None

    @model_validator(mode="after")
    def _says_which(self) -> "Attestation":
        if self.kind is AttestationKind.REPRODUCED and not (self.reading or "").strip():
            raise ValueError("a reproduced symptom cites the reading that reproduced it")
        if self.kind is AttestationKind.REPORTED:
            if self.reading:
                raise ValueError(
                    "a reported symptom cites a reading; if a reading reproduced it, say reproduced"
                )
            if not (self.reported_by or "").strip():
                raise ValueError("a reported symptom must say where the report came from")
        return self


class Symptom(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SymptomKind
    subject: str
    description: str | None = None
    source: str
    attestation: Attestation

    @model_validator(mode="after")
    def _subject_is_a_subject(self) -> "Symptom":
        _require_subject(self.subject, "symptom subject")
        return self


class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    subject: str
    status: HypothesisStatus
    reason: str | None = None
    #: the readings that moved it off `open`.
    readings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _a_moved_hypothesis_says_what_moved_it(self) -> "Hypothesis":
        _require_subject(self.subject, f"hypothesis {self.id} subject")
        moved = self.status in (HypothesisStatus.RULED_OUT, HypothesisStatus.SUPPORTED)
        if moved and not self.readings:
            raise ValueError(
                f"hypothesis {self.id} is {self.status.value} with no reading behind it"
            )
        if self.status is HypothesisStatus.UNEXPLORED and not (self.reason or "").strip():
            raise ValueError(
                f"hypothesis {self.id} is unexplored with no reason. A partial "
                "diagnosis says why it is partial."
            )
        return self


class InvestigationReading(BaseModel):
    """A reading as an investigation holds it: with an id the fault tree
    can cite. The Reading is unchanged — the id is the investigation's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    reading: Reading


class FaultEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_subject: str
    to_subject: str
    relation: Relation
    #: never empty — §2.8's structural guarantee.
    established_by: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _an_edge_joins_two_real_subjects(self) -> "FaultEdge":
        _require_subject(self.from_subject, "fault edge subject")
        _require_subject(self.to_subject, "fault edge subject")
        if self.from_subject == self.to_subject:
            raise ValueError(f"a fault edge cannot join {self.from_subject} to itself")
        if any(not reading_id.strip() for reading_id in self.established_by):
            raise ValueError("a fault edge cites an empty reading id")
        return self


class Criterion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    holds: bool
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _the_reason_is_not_blank(self) -> "Criterion":
        if not self.reason.strip():
            raise ValueError("a confidence criterion gives no reason")
        return self


class ConfidenceRubric(BaseModel):
    """§2.9: four independent booleans, never collapsed into a number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reproduced: Criterion
    discriminated: Criterion
    counterfactual: Criterion
    verified: Criterion

    @model_validator(mode="after")
    def _a_diagnosis_never_claims_verified(self) -> "ConfidenceRubric":
        if self.verified.holds:
            raise ValueError(
                "a diagnosis claims verified. A diagnosis never does: whether it "
                "is verified is a verification's to say, recorded on its own"
            )
        return self


class Diagnosis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root_subject: str
    statement: str = Field(min_length=1)
    confidence: ConfidenceRubric
    remediation: str | None = None
    complete: bool

    @model_validator(mode="after")
    def _the_root_is_a_subject(self) -> "Diagnosis":
        _require_subject(self.root_subject, "diagnosis root")
        return self


class Investigation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    opened_at: datetime
    closed_at: datetime | None = None
    environment: str = Field(min_length=1)
    symptom: Symptom
    hypotheses: tuple[Hypothesis, ...] = ()
    readings: tuple[InvestigationReading, ...] = ()
    fault_tree: tuple[FaultEdge, ...] = ()
    diagnosis: Diagnosis | None = None

    @model_validator(mode="after")
    def _everything_cited_was_measured(self) -> "Investigation":
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError(f"investigation {self.id} closes before it opened")

        reading_ids = [item.id for item in self.readings]
        if len(reading_ids) != len(set(reading_ids)):
            raise ValueError(f"investigation {self.id} holds two readings with one id")
        taken = set(reading_ids)

        hypothesis_ids = [hypothesis.id for hypothesis in self.hypotheses]
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError(f"investigation {self.id} has two hypotheses with one id")
        for hypothesis in self.hypotheses:
            missing = set(hypothesis.readings) - taken
            if missing:
                raise ValueError(
                    f"hypothesis {hypothesis.id} cites {sorted(missing)}, which this "
                    "investigation did not take"
                )

        for edge in self.fault_tree:
            missing = set(edge.established_by) - taken
            if missing:
                raise ValueError(
                    f"fault edge {edge.from_subject} -[{edge.relation.value}]-> "
                    f"{edge.to_subject} cites {sorted(missing)}, which this "
                    "investigation did not take"
                )

        attestation = self.symptom.attestation
        if attestation.kind is AttestationKind.REPRODUCED:
            cited = next((item for item in self.readings if item.id == attestation.reading), None)
            if cited is None:
                raise ValueError(
                    f"the symptom is attested as reproduced by {attestation.reading!r}, which "
                    "this investigation did not take"
                )
            if cited.reading.verdict != "fail" or cited.reading.target != self.symptom.subject:
                raise ValueError(
                    f"the symptom is attested as reproduced by {attestation.reading}, which is "
                    f"not a failing reading of {self.symptom.subject}. A symptom only reported "
                    "is never presented as reproduced."
                )

        if self.diagnosis is not None and self.diagnosis.complete:
            root = self.diagnosis.root_subject
            if not any(root in (edge.from_subject, edge.to_subject) for edge in self.fault_tree):
                raise ValueError(
                    f"a complete diagnosis names root {root}, which no fault edge "
                    "reaches. A root the readings did not establish is a guess."
                )
        return self
