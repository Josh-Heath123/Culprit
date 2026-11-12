"""The latency rule (Phase 36 part 1), held to the fixture Go reads too.

Verdicts and reasons must match exactly in both languages, so the fixture
carries both. The ranks are also checked here against the binomial worked
by hand, so the fixture is not only the implementation agreeing with
itself, and moving a bound one rank is shown to turn it red.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from culprit_model import latency
from culprit_model.latency import (
    BUDGET_PREDICATES,
    Budget,
    LatencyShapeError,
    judge,
    lower_rank,
    upper_rank,
)
from culprit_model.readings import Reading
from culprit_model.subjects import build
from pydantic import ValidationError

#: Built, never hand-formatted (scripts/tests/test_subject_construction.py).
READY = build("http", component="inventory-service", method="GET", path="/ready")

FIXTURE = json.loads(
    (Path(__file__).parent / "latency_conformance.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURE["judged"], ids=lambda case: case["why"][:60])
def test_the_rule_gives_the_fixtures_verdict_and_reason(case: dict) -> None:
    assert judge(case["measured"], case["expected"]) == (case["verdict"], case["reason"])


@pytest.mark.parametrize("case", FIXTURE["rejected"], ids=lambda case: case["why"][:60])
def test_inputs_that_are_not_the_rules_are_refused(case: dict) -> None:
    with pytest.raises(LatencyShapeError):
        judge(case["measured"], case["expected"])


def test_the_fixture_covers_the_cases_the_brief_names() -> None:
    whys = " | ".join(case["why"] for case in FIXTURE["judged"])
    verdicts = {case["verdict"] for case in FIXTURE["judged"]}
    assert verdicts == {"pass", "fail", "inconclusive"}
    for named in ("well under", "well over", "straddling", "too few samples", "timeout", "floor"):
        assert named in whys, named


def test_the_ranks_are_the_binomials_worked_by_hand() -> None:
    # p50 from 20: P(Bin(20, .5) >= 7) = .942 and >= 8 is .868, so the
    # lower bound is the 7th; P(Bin <= 13) = .942 and <= 12 is .868, so the
    # upper is the 14th.
    assert (lower_rank(20, 50), upper_rank(20, 50)) == (7, 14)
    # p95: 1 - .95^n >= .9 needs n >= 45, so the 45th of 45 is the upper
    # bound and 44 samples have none (the plan's floor).
    assert upper_rank(45, 95) == 45
    assert upper_rank(44, 95) is None
    assert upper_rank(50, 95) == 50
    # One answer: no bound either side at 90%.
    assert (lower_rank(1, 50), upper_rank(1, 50)) == (None, None)


@pytest.mark.parametrize("shift", ["lower", "upper"])
def test_moving_a_bound_one_rank_turns_the_fixture_red(
    shift: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = {"lower": lower_rank, "upper": upper_rank}[shift]

    def moved(n: int, percentile: int) -> int | None:
        rank = original(n, percentile)
        if rank is None:
            return None
        return rank + 1 if shift == "lower" else max(rank - 1, 1)

    monkeypatch.setattr(latency, f"{shift}_rank", moved)
    differing = [
        case["why"]
        for case in FIXTURE["judged"]
        if judge(case["measured"], case["expected"]) != (case["verdict"], case["reason"])
    ]
    assert differing, f"moving the {shift} bound one rank changed no case"


# ---- budgets -------------------------------------------------------------------


def test_a_budget_names_a_known_predicate_and_a_canonical_subject() -> None:
    budget = Budget(
        subject=READY,
        predicate="latency_p95_ms",
        value=300,
        why="the route the walk asks",
    )
    assert budget.value == 300
    assert set(BUDGET_PREDICATES) == {"latency_p50_ms", "latency_p95_ms"}


@pytest.mark.parametrize(
    "fields",
    [
        {"predicate": "latency_p99_ms"},
        {"predicate": "latency_ms"},
        {"value": 0},
        {"value": 2.5},
        {"value": "300"},
        {"why": ""},
        # Not canonical: the built subject with its component re-cased.
        {"subject": READY.replace("inventory-service", "Inventory-Service")},
        {"subject": "not a subject"},
    ],
)
def test_a_budget_is_refused_unless_it_is_well_formed(fields: dict) -> None:
    good = {
        "subject": READY,
        "predicate": "latency_p95_ms",
        "value": 300,
        "why": "w",
    }
    with pytest.raises(ValidationError):
        Budget(**{**good, **fields})


# ---- readings ------------------------------------------------------------------


def _reading(verdict: str, measured: dict, expected: dict | None, reason: str = "r") -> dict:
    return {
        "probe_id": "probe.http.latency",
        "probe_version": 1,
        "target": READY,
        "environment": "local",
        "verdict": verdict,
        "measured": measured,
        "expected": expected,
        "reason": reason,
        "taken_at": datetime(2026, 11, 12, tzinfo=UTC),
        "agent_id": "culprit-cli",
    }


@pytest.mark.parametrize("case", FIXTURE["judged"], ids=lambda case: case["why"][:60])
def test_a_reading_with_its_rules_verdict_is_accepted(case: dict) -> None:
    Reading.model_validate(_reading(case["verdict"], case["measured"], case["expected"]))


@pytest.mark.parametrize("case", FIXTURE["judged"], ids=lambda case: case["why"][:60])
def test_a_reading_whose_verdict_its_samples_do_not_give_is_refused(case: dict) -> None:
    for verdict in {"pass", "fail", "inconclusive"} - {case["verdict"]}:
        with pytest.raises(ValidationError, match="its own samples and budget give"):
            Reading.model_validate(_reading(verdict, case["measured"], case["expected"]))


def test_a_latency_verdict_without_samples_is_refused_and_could_not_tell_is_not() -> None:
    with pytest.raises(ValidationError, match="must carry the samples"):
        Reading.model_validate(_reading("pass", {"url": "http://x/ready"}, None))
    Reading.model_validate(_reading("inconclusive", {"url": "http://x/ready"}, None))


def test_a_refused_latency_reading_carries_no_samples_and_is_not_judged() -> None:
    Reading.model_validate(_reading("refused", {}, None))
