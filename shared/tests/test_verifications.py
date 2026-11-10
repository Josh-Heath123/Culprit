"""The Phase 34 Verification contract, held to the Go side by a shared fixture.

`cli/internal/model/verification_test.go` reads the same file.
"""

import json
from pathlib import Path

import pytest
from culprit_model.verifications import (
    Change,
    ChangeKind,
    Verification,
    VerificationVerdict,
)
from pydantic import ValidationError

FIXTURE = json.loads(
    (Path(__file__).parent / "verification_conformance.json").read_text(encoding="utf-8")
)


def test_the_verdicts_match_the_shared_fixture() -> None:
    assert FIXTURE["verdicts"] == [v.value for v in VerificationVerdict]


def test_the_change_kinds_match_the_shared_fixture() -> None:
    assert FIXTURE["change_kinds"] == [k.value for k in ChangeKind]


@pytest.mark.parametrize("case", FIXTURE["touches"], ids=lambda c: f"{c['change']}~{c['subject']}")
def test_what_a_change_touches(case: dict) -> None:
    assert Change.model_validate(case["change"]).touches(case["subject"]) is case["touches"]


@pytest.mark.parametrize("case", FIXTURE["verifications_accepted"], ids=lambda c: c["why"][:70])
def test_verifications_the_fixture_accepts_are_accepted(case: dict) -> None:
    Verification.model_validate(case["verification"])


@pytest.mark.parametrize("case", FIXTURE["verifications_rejected"], ids=lambda c: c["why"][:70])
def test_verifications_the_fixture_rejects_are_rejected(case: dict) -> None:
    with pytest.raises(ValidationError):
        Verification.model_validate(case["verification"])


def test_every_verdict_has_an_accepted_case() -> None:
    seen = {case["verification"]["verdict"] for case in FIXTURE["verifications_accepted"]}
    assert seen == {v.value for v in VerificationVerdict}


def test_a_verified_with_each_clause_false_is_in_the_fixture() -> None:
    whys = [case["why"] for case in FIXTURE["verifications_rejected"]]
    for clause in ("first", "second", "third"):
        assert any(f"verified with its {clause} clause false" in why for why in whys), clause
