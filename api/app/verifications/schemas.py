"""Bodies for the verification routes and `GET /outcomes/accuracy`.

The verification itself is `culprit_model.verifications.Verification` —
exactly what `culprit verify --format json` writes, and what an agent's
`verify` task builds. Parsing it judges it: the model refuses a
verification whose verdict or clause flags its own record does not reach,
so the API stores no verdict the Python rule disagrees with.
"""

from datetime import datetime
from typing import Literal

from culprit_model.verifications import Verification
from pydantic import BaseModel, ConfigDict

#: Whether the fault verified was planted — a drill, the fault library, a
#: quickstart — or happened on a real system. Said by whoever asks for the
#: verification; never guessed, and never defaulted.
Source = Literal["planted", "real"]


class VerificationSubmitted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Source
    verification: Verification


class VerificationStored(BaseModel):
    id: str
    verdict: str


class StoredVerification(BaseModel):
    """A verification as the control plane holds it, with who stored it."""

    verification: Verification
    source: Source
    #: "project-token", or "agent:<id>".
    submitted_by: str
    ingested_at: datetime


class VerificationList(BaseModel):
    """Newest first: the first item is the one the rubric's `verified`
    comes from."""

    investigation_id: str
    items: list[StoredVerification]


class VerdictCounts(BaseModel):
    verified: int = 0
    not_resolved: int = 0
    regressed: int = 0
    changed_underneath: int = 0
    inconclusive: int = 0


class ClassAccuracy(BaseModel):
    #: The subject kind of the diagnosis's root — `auth`, `connection`,
    #: `http`, `config`, `component`, ... — derived from the stored
    #: investigation, never from whoever posted the verification.
    fault_class: str
    source: Source
    #: Every outcome counted in this row, of every verdict.
    outcomes: int
    verdicts: VerdictCounts
    #: Outcomes with a verdict other than inconclusive: the denominator.
    decided: int
    #: verified / decided; None when nothing was decided.
    verified_share: float | None
    #: Beside the share, never folded into it.
    inconclusive: int


class Accuracy(BaseModel):
    method: str
    #: Outcomes counted, every class and source together.
    outcomes: int
    #: Investigations verified whose diagnosis was partial: not outcomes,
    #: so not counted above, and said rather than hidden.
    partial_diagnoses_not_counted: int
    classes: list[ClassAccuracy]
    #: Set when there is nothing to report, saying so in words.
    statement: str | None = None
