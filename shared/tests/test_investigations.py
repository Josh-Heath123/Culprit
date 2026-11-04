"""The §2.8 Investigation contract, held to the Go side by a shared fixture.

`cli/internal/model/investigation_test.go` reads the same file. An
investigation `culprit diagnose` writes and the API refuses is a diagnosis
that vanishes between the walk that made it and the place meant to keep it.
"""

import json
from pathlib import Path

import pytest
from culprit_model import subjects
from culprit_model.investigations import (
    AttestationKind,
    FaultEdge,
    HypothesisStatus,
    Investigation,
    Relation,
    SymptomKind,
)
from culprit_model.readings import HYPOTHESIS_KINDS
from pydantic import ValidationError

FIXTURE = json.loads(
    (Path(__file__).parent / "investigation_conformance.json").read_text(encoding="utf-8")
)


def test_the_relation_set_matches_the_shared_fixture() -> None:
    assert set(FIXTURE["relations"]) == {r.value for r in Relation}


def test_the_hypothesis_status_set_matches_the_shared_fixture() -> None:
    assert set(FIXTURE["hypothesis_statuses"]) == {s.value for s in HypothesisStatus}


def test_the_hypothesis_kinds_match_the_shared_fixture() -> None:
    assert set(FIXTURE["hypothesis_kinds"]) == HYPOTHESIS_KINDS


def test_the_attestation_kinds_match_the_shared_fixture() -> None:
    assert set(FIXTURE["attestation_kinds"]) == {k.value for k in AttestationKind}


def test_the_symptom_kind_set_matches_the_shared_fixture() -> None:
    assert set(FIXTURE["symptom_kinds"]) == {k.value for k in SymptomKind}


@pytest.mark.parametrize("case", FIXTURE["investigations_accepted"], ids=lambda c: c["why"][:60])
def test_investigations_the_fixture_accepts_are_accepted(case: dict) -> None:
    Investigation.model_validate(case["investigation"])


@pytest.mark.parametrize("case", FIXTURE["investigations_rejected"], ids=lambda c: c["why"][:60])
def test_investigations_the_fixture_rejects_are_rejected(case: dict) -> None:
    with pytest.raises(ValidationError):
        Investigation.model_validate(case["investigation"])


COMPONENT = subjects.build("component", name="orders")
CONFIG_KEY = subjects.build("config", component="orders", key="DATABASE_URL")


def test_a_fault_edge_with_no_reading_cannot_be_constructed() -> None:
    with pytest.raises(ValidationError):
        FaultEdge(
            from_subject=COMPONENT,
            to_subject=CONFIG_KEY,
            relation=Relation.CAUSED_BY,
            established_by=(),
        )
    edge = FaultEdge(
        from_subject=COMPONENT,
        to_subject=CONFIG_KEY,
        relation=Relation.CAUSED_BY,
        established_by=("r1",),
    )
    assert edge.established_by == ("r1",)
