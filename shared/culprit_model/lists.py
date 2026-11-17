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


# ---- the spec's lists -----------------------------------------------------
#
# response_list is the rule both OpenAPI readers apply to one operation, the
# twin of model.ResponseList in cli/internal/model/lists.go, and held with it
# to shared/tests/list_conformance.json. The rule, in order: the
# first 2xx response in sorted order ($ref resolved); in OpenAPI 3 the
# schema of its first JSON media type in sorted order, in Swagger 2 its own
# schema; local $refs only, at most _MAX_REF_HOPS; a `type: array` schema is
# the list, an object with exactly one `type: array` property is an envelope
# around it; the bound is maxItems when it is a whole number from 0 to
# 2**31 - 1, else None. Anything else is no list.

_MAX_REF_HOPS = 16
_MAX_BOUND = 2**31 - 1


def _is_2xx(code: str) -> bool:
    if code in ("2XX", "2xx"):
        return True
    return len(code) == 3 and code[0] == "2" and code[1:].isascii() and code[1:].isdigit()


def _is_json_media_type(media_type: str) -> bool:
    base = media_type.lower().split(";", 1)[0].strip()
    return base == "application/json" or base.endswith("+json")


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]


def _resolve(document: dict[str, Any], node: Any) -> dict[str, Any] | None:
    for _ in range(_MAX_REF_HOPS + 1):
        if not isinstance(node, dict):
            return None
        if "$ref" not in node:
            return node
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return None
        node = document
        for token in _pointer_tokens(ref[1:]):
            if not isinstance(node, dict) or token not in node:
                return None
            node = node[token]
    return None


def _max_items(schema: dict[str, Any]) -> int | None:
    value = schema.get("maxItems")
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int) or value < 0 or value > _MAX_BOUND:
        return None
    return value


def response_list(document: dict[str, Any], operation: dict[str, Any]) -> tuple[bool, int | None]:
    """Whether the operation answers a list, and its bound (None: unbounded)."""
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return False, None
    codes = sorted(code for code in responses if isinstance(code, str) and _is_2xx(code))
    if not codes:
        return False, None
    response = _resolve(document, responses[codes[0]])
    if response is None:
        return False, None
    content = response.get("content")
    if isinstance(content, dict):
        types = sorted(t for t in content if isinstance(t, str) and _is_json_media_type(t))
        if not types:
            return False, None
        media = content[types[0]]
        schema = media.get("schema") if isinstance(media, dict) else None
    else:
        schema = response.get("schema")
    resolved = _resolve(document, schema)
    if resolved is None:
        return False, None
    if resolved.get("type") == "array":
        return True, _max_items(resolved)
    properties = resolved.get("properties")
    if not isinstance(properties, dict) or ("type" in resolved and resolved["type"] != "object"):
        return False, None
    lists = [
        candidate
        for candidate in (_resolve(document, value) for value in properties.values())
        if candidate is not None and candidate.get("type") == "array"
    ]
    if len(lists) != 1:
        return False, None
    return True, _max_items(lists[0])
