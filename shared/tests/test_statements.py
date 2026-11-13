"""The statement rule (Phase 37 part 2), held to the fixture the Go rule
(cli/internal/model/statements.go) is held to."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from culprit_model.latency import LatencyShapeError
from culprit_model.readings import Reading
from culprit_model.statements import STATEMENT_PROBE_ID, judge_statements
from culprit_model.subjects import build

CASES = json.loads(
    (Path(__file__).parent / "statement_conformance.json").read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["why"])
def test_the_statement_rule_holds_to_the_shared_cases(case: dict) -> None:
    if case.get("error"):
        with pytest.raises(LatencyShapeError):
            judge_statements(case["measured"])
        return
    assert judge_statements(case["measured"]) == (case["verdict"], case["reason"])


def _reading(verdict: str) -> dict:
    return {
        "probe_id": STATEMENT_PROBE_ID,
        "probe_version": 1,
        "target": build("component", name="inventory-db"),
        "environment": "local",
        "verdict": verdict,
        "reason": "judged",
        "measured": {
            "reset_during_window": False,
            "statements": [{"queryid": "101", "calls": 5, "total_us": 260000, "budget_ms": 50}],
        },
        "taken_at": datetime(2026, 11, 12, tzinfo=UTC),
        "agent_id": "test",
    }


def test_a_statement_reading_whose_verdict_disagrees_is_refused() -> None:
    with pytest.raises(ValueError, match="its own integers give fail"):
        Reading(**_reading("pass"))
    assert Reading(**_reading("fail")).verdict.value == "fail"
