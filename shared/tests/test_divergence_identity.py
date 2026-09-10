"""The Go and Python divergence identities must agree, byte for byte.

Read from the same fixture `cli/internal/model/divergence_identity_test.go`
reads. The arrangement is deliberate and is the one subject URIs already
use: two implementations of one identity, held together by a file, so
changing one without the other fails a test rather than producing
duplicate history nobody notices.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from culprit_model.facts import Divergence, DivergenceKind, Fact, Provenance
from culprit_model.planes import ConfidenceRank, Plane, SourceKind

FIXTURE = Path(__file__).parent / "divergence_identity_conformance.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _fact(subject: str, predicate: str, extractor: str, artefact: str) -> Fact:
    return Fact(
        plane=Plane.INTENT,
        subject=subject,
        predicate=predicate,
        value=True,
        provenance=Provenance(
            source_kind=SourceKind.STATIC,
            extractor=extractor,
            artefact=artefact or None,
            confidence_rank=ConfidenceRank.STATIC_FRAMEWORK_CODE,
        ),
        captured_at=datetime.now(UTC),
        capture_id=UUID("00000000-0000-4000-8000-00000000c0de"),
    )


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_identity_matches_the_shared_fixture(case: dict) -> None:
    divergence = Divergence(
        kind=DivergenceKind.INTENT_CONFLICT,
        subject=case["subject"],
        predicate=case["predicate"],
        left=_fact(
            case["subject"], case["predicate"],
            case["left_extractor"], case["left_artefact"],
        ),
        right=_fact(
            case["subject"], case["predicate"],
            case["right_extractor"], case["right_artefact"],
        ),
    )
    assert divergence.identity() == case["identity"]


def test_every_fixture_identity_is_distinct() -> None:
    """Otherwise the fixture cannot detect the collision it covers.

    Two of the cases share a subject, a predicate and both extractors,
    and differ only in the right-hand artefact. If the identity dropped
    the artefact again, those two would collapse and every other
    assertion here would still pass.
    """
    identities = [case["identity"] for case in CASES]
    assert len(set(identities)) == len(identities), "two fixture cases share an identity"
