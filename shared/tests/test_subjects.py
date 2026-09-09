"""Conformance tests for subject-URI construction (§2.3).

Table-driven off `subject_conformance.json` rather than inline cases, so
the Go implementation Phase 28 adds is held to the same table instead of
to a re-typed approximation of it. A new case goes in the JSON file.

Runs inside api's pytest (see api/pyproject.toml's `testpaths`) — the
same arrangement `scripts/tests/` already uses, rather than standing up
a third test entry point for a package with no dependencies of its own.
"""

import json
from pathlib import Path

import pytest
from culprit_model import build, parse
from culprit_model.subjects import SubjectError

_FIXTURE = json.loads((Path(__file__).parent / "subject_conformance.json").read_text())


def _case_id(case: dict) -> str:
    return case.get("why", case.get("subject", case.get("kind", "case")))


@pytest.mark.parametrize("case", _FIXTURE["build"], ids=_case_id)
def test_build_matches_conformance_fixture(case: dict) -> None:
    assert build(case["kind"], **case["parts"]) == case["subject"]


@pytest.mark.parametrize("case", _FIXTURE["build"], ids=_case_id)
def test_build_is_idempotent_through_parse(case: dict) -> None:
    """`build(*parse(s)) == s` for everything `build` produces.

    This is what stops the two halves drifting: a builder change that
    parse() can't read back is caught here, not by a Phase 29 report
    quietly failing to join two facts that describe the same route.
    """
    subject = build(case["kind"], **case["parts"])
    kind, parts = parse(subject)
    assert build(kind, **parts) == subject


@pytest.mark.parametrize("case", _FIXTURE["build_errors"], ids=_case_id)
def test_build_rejects_bad_input(case: dict) -> None:
    with pytest.raises((SubjectError, ValueError)):
        build(case["kind"], **case["parts"])


@pytest.mark.parametrize("case", _FIXTURE["parse_errors"], ids=_case_id)
def test_parse_rejects_bad_input(case: dict) -> None:
    with pytest.raises(SubjectError):
        parse(case["subject"])


def test_four_frameworks_agree_on_one_subject() -> None:
    """The point of the whole module, stated as one assertion.

    An OpenAPI document, an Express router, a Flask decorator and a
    Django `re_path` describing the same route must produce one subject —
    otherwise nothing they each assert about it will ever be compared.
    """
    subjects = {
        build("http", component="orders-svc", method="GET", path=path)
        for path in (
            "/orders/{order_id}",
            "/orders/:orderId",
            "/orders/<int:order_id>",
            r"^orders/(?P<order_id>[0-9]+)/$",
        )
    }
    assert subjects == {"http:orders-svc/GET /orders/{}"}
