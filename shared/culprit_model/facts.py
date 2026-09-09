"""Fact, Provenance and Divergence — the atomic units of the model.

docs/DIAGNOSTIC_PLAN.md §2.2 and §2.5. Pydantic models rather than plain
dataclasses for the same reason `culprit_shared/raw_event.py` is: these
cross a process boundary (extractor subprocess -> CLI -> API -> Postgres)
and the validation is the contract, not decoration on top of it.

Two invariants are enforced here rather than left to the caller, because
both have a silent-wrong-answer failure mode:

1. An INTENT fact may not carry an environment, and a CONFIGURED or
   OBSERVED fact must (§0.2 — INTENT is what the system is *supposed* to
   do, which is environment-independent by definition). The schema
   encodes the same rule: `intent_facts` has no `environment` column.
2. A Divergence's two sides must be about the same subject+predicate.
   A divergence between two unrelated facts is not a weaker finding, it
   is a meaningless one.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.canonical import canonical_value
from culprit_model.planes import Plane, SourceKind


class Provenance(BaseModel):
    """Where a Fact came from, precisely enough to go and look.

    `artefact` and `locator` are what turn a report line into something a
    developer can open: "openapi.json" plus "$.paths./orders.post", or
    "api/app/main.py" plus "L142".
    """

    model_config = ConfigDict(frozen=True)

    source_kind: SourceKind
    extractor: str
    artefact: str | None = None
    locator: str | None = None
    #: §2.4's ranks are the named landmarks, not a closed set — an
    #: extractor may report any 0..100. Only meaningful for INTENT facts;
    #: CONFIGURED/OBSERVED are readings of a real system rather than
    #: claims about what it should be, which is why `configured_facts`
    #: has no such column.
    confidence_rank: int = Field(ge=0, le=100)


class Fact(BaseModel):
    """A single claim, on one plane, about one subject."""

    model_config = ConfigDict(frozen=True)

    plane: Plane
    subject: str
    predicate: str
    value: Any = None
    environment: str | None = None
    provenance: Provenance
    captured_at: datetime
    capture_id: UUID

    @model_validator(mode="after")
    def _environment_matches_plane(self) -> "Fact":
        if self.plane.requires_environment and not self.environment:
            raise ValueError(f"a {self.plane} fact requires an environment")
        if not self.plane.requires_environment and self.environment:
            raise ValueError(
                f"a {self.plane} fact must not carry an environment "
                f"(got {self.environment!r}) — INTENT is environment-independent"
            )
        return self

    @property
    def canonical(self) -> Any:
        """The value as comparison sees it (`canonical.canonical_value`)."""
        return canonical_value(self.value)


class DivergenceKind(StrEnum):
    """§2.5. `INTENT_CONFLICT` is the one worth reading twice: two INTENT
    sources disagreeing is a finding in its own right (§0.3), not
    something a confidence rank silently resolves by picking a winner.

    `BASELINE_DEVIATION` compares OBSERVED against a statistic derived
    from OBSERVED — it is emphatically not a fourth plane (§2 decisions
    register), which is why it is a divergence *kind* and nothing more.
    """

    INTENT_CONFLICT = "intent_conflict"
    INTENT_VS_CONFIGURED = "intent_vs_configured"
    INTENT_VS_OBSERVED = "intent_vs_observed"
    CONFIGURED_VS_OBSERVED = "configured_vs_observed"
    ENV_VS_ENV = "env_vs_env"
    BASELINE_DEVIATION = "baseline_deviation"


class Severity(StrEnum):
    """Computed deterministically from the system model (§2.5), never an
    LLM judgement: a divergence on a subject that lies on a known request
    path is `BREAKS_REQUEST_PATH`; one on an unreferenced config key is
    `COSMETIC`. `UNKNOWN` is honest and expected until Phase 27's system
    model exists to rank against.
    """

    BREAKS_REQUEST_PATH = "breaks_request_path"
    DEGRADES = "degrades"
    COSMETIC = "cosmetic"
    UNKNOWN = "unknown"


class DivergenceStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class Divergence(BaseModel):
    """Two facts about the same subject+predicate that disagree."""

    model_config = ConfigDict(frozen=True)

    id: UUID | None = None
    kind: DivergenceKind
    subject: str
    predicate: str
    left: Fact
    right: Fact
    severity: Severity = Severity.UNKNOWN
    first_seen_at: datetime | None = None
    status: DivergenceStatus = DivergenceStatus.OPEN

    @model_validator(mode="after")
    def _sides_are_comparable(self) -> "Divergence":
        if self.left.subject != self.right.subject:
            raise ValueError(
                f"divergence sides disagree on subject: "
                f"{self.left.subject!r} vs {self.right.subject!r}"
            )
        if self.left.predicate != self.right.predicate:
            raise ValueError(
                f"divergence sides disagree on predicate: "
                f"{self.left.predicate!r} vs {self.right.predicate!r}"
            )
        if self.subject != self.left.subject or self.predicate != self.left.predicate:
            raise ValueError("divergence subject/predicate must match its own facts")
        return self
