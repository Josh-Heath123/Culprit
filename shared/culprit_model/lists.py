"""Lists — Phase 38 part 2 (docs/PERFORMANCE_PLAN.md, "Part 2 — lists").

A list route is bounded only where a bound is declared: `maxItems` in the
spec (the INTENT fact `response_list`), or a `response_items_max` budget in
culprit.yaml. `probe.http.response_items` counts the items one GET answers;
its verdict is a pure function of its own measured and expected, by
`judge_response_items` here and `model.JudgeResponseItems` in Go
(cli/internal/model/lists.go), which hold the same rule.
"""

from typing import Any

#: The budgets on how many items a route answers: a whole number of items,
#: on a GET route's http: subject, with an optional `at:` JSON pointer.
LIST_BUDGET_PREDICATES: frozenset[str] = frozenset({"response_items_max"})

#: The largest list budget, in items. Go holds the same number.
MAX_LIST_ITEMS = 1_000_000

#: The longest `at:`, in bytes.
MAX_POINTER_BYTES = 256

RESPONSE_ITEMS_PROBE_ID = "probe.http.response_items"

#: The spec's own list, from either OpenAPI reader: {"max_items": int | None}.
RESPONSE_LIST_PREDICATE = "response_list"

_NOT_COUNTED = {
    "status": "the route answered {status}, not 2xx, so no list was counted",
    "not_json": "the response is not JSON, so no list was counted",
    "no_array": "the response holds no array at {where}, so no list was counted",
    "too_large": "the response is larger than the 1 MiB this probe reads, so no list was counted",
}


class ListShapeError(ValueError):
    """A reading or expectation that is not the rule's input."""


def json_pointer_problem(pointer: str) -> str | None:
    """Why `pointer` is not a budget's `at:`, or None. An RFC 6901 pointer
    written from its first "/"; the whole document is `at:` left out."""
    if not pointer.startswith("/"):
        return "`at` is a JSON pointer starting with /; leave it out for a top-level list"
    if len(pointer.encode("utf-8")) > MAX_POINTER_BYTES:
        return f"`at` is at most {MAX_POINTER_BYTES} bytes"
    data = pointer.encode("utf-8")
    for index, byte in enumerate(data):
        if byte < 0x20 or byte == 0x7F:
            return "`at` holds a control character"
        if byte == ord("~") and (index + 1 >= len(data) or data[index + 1] not in b"01"):
            return "`at` has a ~ that is not ~0 or ~1"
    return None


def _whole(value: Any, name: str, minimum: int, maximum: int) -> int:
    # bool is an int in Python; a JSON true is not a count.
    if isinstance(value, bool):
        raise ListShapeError(f"{name} must be a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise ListShapeError(f"{name} must be a whole number")
        value = int(value)
    if not isinstance(value, int):
        raise ListShapeError(f"{name} must be a whole number")
    if value < minimum or value > maximum:
        raise ListShapeError(f"{name} must be {minimum} to {maximum}")
    return value


def judge_response_items(measured: dict[str, Any], expected: dict[str, Any]) -> tuple[str, str]:
    """The verdict and reason of a probe.http.response_items reading."""
    bound = _whole(expected.get("response_items_max"), "the bound", 1, MAX_LIST_ITEMS)
    at = measured.get("at")
    if not isinstance(at, str) or expected.get("at") != at:
        raise ListShapeError("the reading's at is not the budget's")
    where = at or "the top level"
    reason = measured.get("not_counted")
    if reason is not None:
        if "items" in measured:
            raise ListShapeError("a reading both counted and not")
        if reason not in _NOT_COUNTED:
            raise ListShapeError(f"not_counted {reason!r} is not a known reason")
        status = None
        if reason == "status":
            status = _whole(measured.get("status"), "status", 100, 599)
        return "inconclusive", _NOT_COUNTED[reason].format(status=status, where=where)
    items = _whole(measured.get("items"), "items", 0, 2**31 - 1)
    if items > bound:
        return "fail", f"the list at {where} holds {items} items, over its bound of {bound}"
    return "pass", ""
