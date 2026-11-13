"""The statement rule — Phase 37 part 2.

`probe.db.statement_budget` takes two snapshots of `pg_stat_statements`, a
fixed window apart, in one session. For each statement it has the change in
calls and in total execution time, in whole microseconds. The rule is
integer comparison, nothing else:

- **fail** when `total_us > budget_ms * 1000 * calls` for a statement;
- **pass** when every statement with a budget is within it;
- **inconclusive** when the statistics were reset, or a statement evicted,
  during the window, or when no call to a budgeted statement fell in it.

There is no interval: `pg_stat_statements` keeps no per-call samples, so a
band would be a number Culprit chose.

The Go half is `cli/internal/model/statements.go`; both are held to
`shared/tests/statement_conformance.json`. `Reading` refuses a statement
reading whose verdict its own integers do not give, so the API refuses one
wherever it arrives.

Deterministic and dependency-free (`.claude/rules/determinism.md`).
"""

from typing import Any

from culprit_model.latency import MAX_BUDGET_MS, LatencyShapeError

STATEMENT_PROBE_ID = "probe.db.statement_budget"
PLAN_PROBE_ID = "probe.db.plan"
#: The most statements one reading keeps, those over budget first.
STATEMENT_READING_MAX = 20
#: Every count a reading holds is at most 2^31 - 1, as in Go, so
#: budget * 1000 * calls fits a signed 64-bit integer there.
_MAX_COUNT = 2**31 - 1


def _bounded(value: Any, name: str, minimum: int, maximum: int) -> int:
    # bool is an int in Python; a JSON true is not a count. A float with no
    # fraction is accepted, because JSON decoded in Go arrives as one.
    if isinstance(value, bool):
        raise LatencyShapeError(f"{name} must be a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise LatencyShapeError(f"{name} must be a whole number")
        value = int(value)
    if not isinstance(value, int) or value < minimum:
        raise LatencyShapeError(f"{name} must be a whole number of at least {minimum}")
    if value > maximum:
        raise LatencyShapeError(f"{name} must be at most {maximum}")
    return value


def statement_inputs(measured: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    reset = measured.get("reset_during_window")
    if not isinstance(reset, bool):
        raise LatencyShapeError("reset_during_window must be true or false")
    raw = measured.get("statements")
    if not isinstance(raw, list):
        raise LatencyShapeError("statements must be a list")
    if len(raw) > STATEMENT_READING_MAX:
        raise LatencyShapeError(f"a reading keeps at most {STATEMENT_READING_MAX} statements")
    out = []
    for index, statement in enumerate(raw):
        if not isinstance(statement, dict):
            raise LatencyShapeError(f"statements[{index}] must be an object")
        query_id = statement.get("queryid")
        if not isinstance(query_id, str) or not query_id:
            raise LatencyShapeError(f"statements[{index}].queryid must be text")
        calls = _bounded(statement.get("calls"), f"statements[{index}].calls", 1, _MAX_COUNT)
        total = _bounded(statement.get("total_us"), f"statements[{index}].total_us", 0, _MAX_COUNT)
        budget = 0
        if "budget_ms" in statement:
            budget = _bounded(
                statement["budget_ms"], f"statements[{index}].budget_ms", 1, MAX_BUDGET_MS
            )
        out.append({"queryid": query_id, "calls": calls, "total_us": total, "budget_ms": budget})
    return reset, out


def judge_statements(measured: dict[str, Any]) -> tuple[str, str]:
    """The verdict and reason for a statement window."""
    reset, statements = statement_inputs(measured)
    if reset:
        return (
            "inconclusive",
            "pg_stat_statements was reset, or a statement evicted from it, during the "
            "window, so no change over it can be trusted",
        )
    judged = 0
    for statement in statements:
        if not statement["budget_ms"]:
            continue
        judged += 1
        if statement["total_us"] > statement["budget_ms"] * 1000 * statement["calls"]:
            return (
                "fail",
                f"statement {statement['queryid']} is over its {statement['budget_ms']} ms "
                f"budget: {statement['total_us']} µs over {statement['calls']} call(s) in the "
                f"window, more than {statement['budget_ms']} ms each",
            )
    if judged == 0:
        return "inconclusive", "no call to a statement with a budget fell in the window"
    return (
        "pass",
        f"every one of {judged} budgeted statement(s) called in the window is within its budget",
    )
