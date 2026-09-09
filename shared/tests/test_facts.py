"""Fact and Divergence invariants (§2.2, §2.5).

Both rules tested here have the same failure mode if left to callers: a
model that validates happily and then produces a comparison nobody can
trust. An INTENT fact tagged with an environment would silently never
match the intent of any *other* environment; a divergence between two
facts about different subjects is not a weak finding, it is a
meaningless one.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from culprit_model import (
    ConfidenceRank,
    Divergence,
    DivergenceKind,
    DivergenceStatus,
    Fact,
    Plane,
    Provenance,
    Severity,
    SourceKind,
    build,
)

_NOW = datetime.now(UTC)
_CAPTURE = uuid4()

# Built, not written out: scripts/tests/test_subject_construction.py
# enforces that nothing outside culprit_model.subjects hand-formats a
# subject URI, and a test file is not exempt from the rule it exists to
# support.
_SUBJECT = build("http", component="orders-svc", method="POST", path="/orders")
_OTHER_SUBJECT = build("http", component="orders-svc", method="GET", path="/orders")


def _provenance(rank: int = ConfidenceRank.COMMITTED_SPEC) -> Provenance:
    return Provenance(
        source_kind=SourceKind.SPEC,
        extractor="culprit-extract-test@0.0.1",
        artefact="openapi.json",
        locator="$.paths./orders.post",
        confidence_rank=rank,
    )


def _fact(plane: Plane, value: object, **overrides: object) -> Fact:
    fields: dict = {
        "plane": plane,
        "subject": _SUBJECT,
        "predicate": "request_schema",
        "value": value,
        "environment": None if plane is Plane.INTENT else "prod",
        "provenance": _provenance(),
        "captured_at": _NOW,
        "capture_id": _CAPTURE,
    }
    fields.update(overrides)
    return Fact(**fields)


def test_intent_fact_may_not_carry_an_environment() -> None:
    with pytest.raises(ValueError, match="environment-independent"):
        _fact(Plane.INTENT, True, environment="prod")


@pytest.mark.parametrize("plane", [Plane.CONFIGURED, Plane.OBSERVED])
def test_non_intent_fact_requires_an_environment(plane: Plane) -> None:
    with pytest.raises(ValueError, match="requires an environment"):
        _fact(plane, True, environment=None)


def test_confidence_rank_is_bounded() -> None:
    with pytest.raises(ValueError):
        Provenance(source_kind=SourceKind.STATIC, extractor="x@1", confidence_rank=101)


def test_fact_canonical_value_uses_the_shared_canonicaliser() -> None:
    left = _fact(Plane.INTENT, {"b": 1, "a": 2})
    right = _fact(Plane.INTENT, {"a": 2, "b": 1})
    assert left.canonical == right.canonical


def test_divergence_requires_both_sides_to_be_about_the_same_thing() -> None:
    left = _fact(Plane.INTENT, {"total_cents": "int"})
    right = _fact(Plane.CONFIGURED, {"total_cents": "text"})
    other_subject = _fact(
        Plane.CONFIGURED, {"total_cents": "text"}, subject=_OTHER_SUBJECT
    )

    Divergence(
        kind=DivergenceKind.INTENT_VS_CONFIGURED,
        subject=left.subject,
        predicate=left.predicate,
        left=left,
        right=right,
    )

    with pytest.raises(ValueError, match="disagree on subject"):
        Divergence(
            kind=DivergenceKind.INTENT_VS_CONFIGURED,
            subject=left.subject,
            predicate=left.predicate,
            left=left,
            right=other_subject,
        )


def test_divergence_defaults_are_the_honest_ones() -> None:
    """Severity starts UNKNOWN and status starts OPEN.

    Severity is computed from the system model (Phase 27), which does not
    exist yet — defaulting to anything else would be a claim the code
    cannot back.
    """
    left = _fact(Plane.INTENT, 1)
    right = _fact(Plane.CONFIGURED, 2)
    divergence = Divergence(
        kind=DivergenceKind.INTENT_VS_CONFIGURED,
        subject=left.subject,
        predicate=left.predicate,
        left=left,
        right=right,
    )
    assert divergence.severity is Severity.UNKNOWN
    assert divergence.status is DivergenceStatus.OPEN


def test_intent_conflict_is_expressible_between_two_intent_facts() -> None:
    """§0.3: two INTENT sources disagreeing is a finding, not something
    the higher confidence rank silently resolves."""
    spec = _fact(Plane.INTENT, {"total_cents": "int"})
    from_tests = _fact(
        Plane.INTENT,
        {"total_cents": "string"},
        provenance=Provenance(
            source_kind=SourceKind.TEST,
            extractor="culprit-extract-test@0.0.1",
            confidence_rank=ConfidenceRank.STATIC_TESTS,
        ),
    )
    divergence = Divergence(
        kind=DivergenceKind.INTENT_CONFLICT,
        subject=spec.subject,
        predicate=spec.predicate,
        left=spec,
        right=from_tests,
    )
    assert divergence.left.provenance.confidence_rank > divergence.right.provenance.confidence_rank
