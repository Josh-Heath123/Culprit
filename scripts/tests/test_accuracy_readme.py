"""The README's accuracy number (Phase 34 part 2): rendered by a committed
command from the fault library's committed results, saying it is planted
faults, with its method and its count — and never stale."""

import json

import accuracy_readme as accuracy
from culprit_model.subjects import build

AUDIENCE = build(
    "auth", from_component="order-service", to_component="inventory-service", aspect="audience"
)
STOCK_ROUTE = build("http", component="inventory-service", method="GET", path="/stock")
ORDER_SERVICE = build("component", name="order-service")


def _results(**override):
    faults = [
        {
            "name": "auth-audience",
            "root_subject": AUDIENCE,
            "complete": True,
            "verdict": "verified",
        },
        {
            "name": "contract",
            "root_subject": STOCK_ROUTE,
            "complete": True,
            "verdict": "not_resolved",
        },
        {
            "name": "latency",
            "root_subject": ORDER_SERVICE,
            "complete": False,
            "verdict": "inconclusive",
        },
    ]
    return {"why": "test", "faults": faults, "scenarios": []} | override


def test_the_readme_is_what_the_committed_results_render() -> None:
    """CI's guard: change the results or the README by hand, and this fails
    until `just accuracy-readme` is run."""
    results = json.loads(accuracy.RESULTS.read_text(encoding="utf-8"))
    readme = accuracy.README.read_text(encoding="utf-8")
    assert accuracy.replaced(readme, accuracy.render(results)) == readme


def test_it_says_the_faults_were_planted_and_not_a_real_systems() -> None:
    section = accuracy.render(_results())
    assert "faults we planted" in section
    assert "They are not accuracy on anyone's real system." in section
    assert "No outcome from a real system is counted here" in section
    assert "**Method.**" in section


def test_it_counts_complete_diagnoses_only_with_the_denominator_stated() -> None:
    section = accuracy.render(_results())
    assert "**1 of 2 planted faults verified fixed** (50%)" in section
    assert "2 outcomes in all" in section
    assert "1 partial diagnoses not counted" in section
    assert "`latency` (inconclusive)" in section
    # One row per class; the partial fault in none of them.
    assert "| `auth` | `auth-audience` | 1 | 1 | 1 | 0 |" in section
    assert "| `http` | `contract` | 1 | 0 | 1 | 0 |" in section
    assert "| `component`" not in section


def test_inconclusive_is_beside_the_share_never_in_it() -> None:
    results = _results()
    results["faults"][1]["verdict"] = "inconclusive"
    section = accuracy.render(results)
    assert "**1 of 1 planted faults verified fixed** (100%)" in section
    assert "1 inconclusive beside that" in section


def test_scenarios_are_listed_and_not_counted() -> None:
    section = accuracy.render(
        _results(
            scenarios=[
                {
                    "name": "wrong-fix",
                    "root_subject": AUDIENCE,
                    "complete": True,
                    "verdict": "not_resolved",
                }
            ]
        )
    )
    assert "`wrong-fix` (not_resolved)" in section
    assert "2 outcomes in all" in section
