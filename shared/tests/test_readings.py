"""The §2.6 Reading and ProbeManifest contract, held to the Go side by a
shared fixture.

`cli/internal/model/reading_test.go` reads the same file. A verdict the
CLI can emit and the API refuses is a reading that vanishes between the
probe that took it and the database meant to keep it.
"""

import json
from pathlib import Path

import pytest
from culprit_model.readings import (
    Cost,
    Effect,
    Evidence,
    ProbeManifest,
    Reading,
    Verdict,
)
from pydantic import ValidationError

FIXTURE = json.loads(
    (Path(__file__).parent / "reading_conformance.json").read_text(encoding="utf-8")
)


def test_the_verdict_set_matches_the_shared_fixture() -> None:
    assert {v["name"] for v in FIXTURE["verdicts"]} == {v.value for v in Verdict}


def test_which_verdicts_need_a_reason_matches_the_fixture() -> None:
    for case in FIXTURE["verdicts"]:
        assert Verdict(case["name"]).needs_reason is case["needs_reason"], case["name"]


def test_the_effect_set_matches_the_shared_fixture() -> None:
    assert {e["name"] for e in FIXTURE["effects"]} == {e.value for e in Effect}


def test_the_cost_set_matches_the_shared_fixture() -> None:
    assert set(FIXTURE["costs"]) == {c.value for c in Cost}


@pytest.mark.parametrize("case", FIXTURE["manifests_accepted"], ids=lambda c: c["id"])
def test_accepted_manifests_validate(case: dict) -> None:
    manifest = ProbeManifest.model_validate(case)
    assert manifest.id == case["id"]


@pytest.mark.parametrize(
    "case", FIXTURE["manifests_rejected"], ids=lambda c: c["why"][:40]
)
def test_rejected_manifests_are_refused(case: dict) -> None:
    with pytest.raises(ValidationError):
        ProbeManifest.model_validate(case["manifest"])


@pytest.mark.parametrize(
    "case", FIXTURE["readings_accepted"], ids=lambda c: c["why"][:40]
)
def test_accepted_readings_validate(case: dict) -> None:
    reading = Reading.model_validate(case["reading"])
    assert reading.probe_id == case["reading"]["probe_id"]


@pytest.mark.parametrize(
    "case", FIXTURE["readings_rejected"], ids=lambda c: c["why"][:40]
)
def test_rejected_readings_are_refused(case: dict) -> None:
    with pytest.raises(ValidationError):
        Reading.model_validate(case["reading"])


def test_no_probe_may_declare_mutate() -> None:
    """§2.6: 'effect: mutate fails manifest validation. No exceptions in
    this plan.' Asserted directly as well as through the fixture, because
    this is the one rule a future reader is most likely to want to find by
    name."""
    with pytest.raises(ValidationError, match="mutate"):
        ProbeManifest(
            id="probe.db.truncate",
            version=1,
            effect=Effect.MUTATE,
            timeout_ms=1000,
        )


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://admin:hunter2@db.internal:5432/orders",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig",
        "ghp_0123456789abcdefghijklmnopqrstuvwx",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_evidence_may_not_smuggle_a_credential_past_the_redaction_flag(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="redacted"):
        Evidence(kind="authorization", value=value)


def test_the_redaction_heuristic_is_a_net_not_a_proof() -> None:
    """`looks_like_credential` matches known key shapes, so a novel one
    passes. Recorded in `docs/LIMITS.md`: this validator is a backstop
    against accident, not a guarantee against a determined caller. The
    real guarantee is that probes build evidence from closed vocabulary
    and never echo a token — asserted separately, per probe."""
    assert Evidence(kind="opaque", value="sk-live-abcdef0123456789").redacted is False


def test_evidence_describing_a_credential_is_fine() -> None:
    evidence = Evidence(kind="authorization", value="<redacted>", redacted=True)
    assert evidence.redacted
