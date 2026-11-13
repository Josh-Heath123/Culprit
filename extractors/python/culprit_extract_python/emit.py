"""Building Facts, so no reader in this package has to.

One place that knows the capture id, the timestamp, the component name
and the extractor identity — and one place that constructs a config
fact, which is the only construction with a rule attached to it.

`FactBuilder.config_fact` takes a `ValueShape` and has no parameter a
literal value could travel through. That is deliberate and is the
reason this class exists rather than each reader assembling `Fact(...)`
itself: a guarantee that depends on every call site remembering it is
not a guarantee.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from culprit_model.facts import Fact, Provenance
from culprit_model.planes import ConfidenceRank, Plane, SourceKind
from culprit_model.shape import ValueShape


@dataclass
class FactBuilder:
    """Stamps every fact a reader produces with the run's identity."""

    component: str
    capture_id: UUID
    captured_at: datetime
    extractor: str
    #: What was imported to produce introspected facts, e.g.
    #: `app.main:app`. Recorded as the artefact so a reader of the report
    #: knows which module the claim came out of.
    app_target: str = ""
    #: Collected as readers go, so the caller can report both halves.
    problems: list[str] = field(default_factory=list)
    #: The database the orchestrator says this component's schema facts
    #: are on (Q34). Empty only from an older orchestrator.
    database: str = ""

    @property
    def schema_database(self) -> str:
        """The `database` part of this component's `schema:` subjects: the
        name the orchestrator derived from the model, or, from an older
        orchestrator that sends none, `<component>-db`."""
        return self.database or f"{self.component}-db"

    def fact(
        self,
        subject: str,
        predicate: str,
        value: Any,
        *,
        source_kind: SourceKind,
        rank: int,
        artefact: str | None = None,
        locator: str | None = None,
    ) -> Fact:
        return Fact(
            plane=Plane.INTENT,
            subject=subject,
            predicate=str(predicate),
            value=value,
            provenance=Provenance(
                source_kind=source_kind,
                extractor=self.extractor,
                artefact=artefact or None,
                locator=locator or None,
                confidence_rank=int(rank),
            ),
            captured_at=self.captured_at,
            capture_id=self.capture_id,
        )

    def config_fact(
        self,
        subject: str,
        predicate: str,
        shape: ValueShape,
        *,
        source_kind: SourceKind = SourceKind.STATIC,
        rank: int = ConfidenceRank.STATIC_FRAMEWORK_CODE,
        artefact: str | None = None,
        locator: str | None = None,
    ) -> Fact:
        """The only way this package says anything about a config key.

        Takes a shape, never a value. There is no `value` parameter to
        pass one through, and `Fact`'s own validator would refuse it
        anyway — belt and braces, because this is the guarantee the
        whole capture bundle's safety rests on.
        """
        return Fact(
            plane=Plane.INTENT,
            subject=subject,
            predicate=str(predicate),
            value_shape=shape,
            provenance=Provenance(
                source_kind=source_kind,
                extractor=self.extractor,
                artefact=artefact or None,
                locator=locator or None,
                confidence_rank=int(rank),
            ),
            captured_at=self.captured_at,
            capture_id=self.capture_id,
        )
