"""Lists (Phase 38 part 2): the spec's lists and the probe's judgement, held
between Python and Go.

shared/tests/list_conformance.json is generated here. Its `response_list`
cases cross a response schema's shape (a top-level array, an envelope with
one, two or no arrays, ...) with how it is reached (inline, a `$ref` to the
schema, to the response, to the array property, a chain, a `$ref` out of
the document) and with every kind of `maxItems`, in OpenAPI 3; and vary the
status codes, the media types and Swagger 2 against the shapes. Each case
records what culprit_model.lists.response_list makes of it, and
cli/internal/model/lists_test.go holds model.ResponseList to the same
record, so the two OpenAPI readers — the Python extractor's (app.openapi(),
rank 90) and the Go reader's (a committed spec, rank 80) — give the same
answer. The anchors below are asserted by hand, so the record is not merely
self-consistent.

Its `judge` cases are probe.http.response_items readings, held the same way
to model.JudgeResponseItems.

After a deliberate change to the rule:

    cd api && uv run python ../shared/tests/test_lists.py --write
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "list_conformance.json"

if __name__ == "__main__":
    sys.path.insert(0, str(ROOT.parent))

from culprit_model.lists import (  # noqa: E402
    ListShapeError,
    json_pointer_problem,
    judge_response_items,
    response_list,
)

SHAPES: dict[str, Any] = {
    "a top-level array": {"type": "array", "items": {"type": "string"}, "<<bound>>": None},
    "an envelope with one array": {
        "type": "object",
        "properties": {
            "products": {"type": "array", "items": {"type": "string"}, "<<bound>>": None},
            "total": {"type": "integer"},
        },
    },
    "an untyped envelope with one array": {
        "properties": {
            "products": {"type": "array", "items": {"type": "string"}, "<<bound>>": None},
        },
    },
    "an envelope with two arrays": {
        "type": "object",
        "properties": {
            "products": {"type": "array", "items": {"type": "string"}, "<<bound>>": None},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    },
    "an envelope with no array": {
        "type": "object",
        "properties": {"total": {"type": "integer", "<<bound>>": None}},
    },
    "a nullable array (a type list)": {
        "type": ["array", "null"],
        "items": {"type": "string"},
        "<<bound>>": None,
    },
    "an optional array (anyOf)": {
        "anyOf": [
            {"type": "array", "items": {"type": "string"}, "<<bound>>": None},
            {"type": "null"},
        ]
    },
    "a string": {"type": "string", "<<bound>>": None},
    "an array typed as a non-object with properties": {
        "type": "string",
        "properties": {"products": {"type": "array", "<<bound>>": None}},
    },
}

BOUNDS: dict[str, Any] = {
    "absent": "<<absent>>",
    "0": 0,
    "50": 50,
    "50.0": 50.0,
    "1.5": 1.5,
    'the text "50"': "50",
    "-1": -1,
    "2^31 - 1": 2**31 - 1,
    "2^31": 2**31,
    "true": True,
    "null": None,
}

REFS = [
    "inline",
    "a $ref to the schema",
    "a $ref to the response",
    "a $ref to the array",
    "a chain of $refs",
    "a $ref out of the document",
    "a dangling $ref",
    "a $ref with an escaped token",
]


def _bound(node: Any, bound: Any) -> Any:
    """Fills <<bound>> with maxItems, or drops it."""
    if isinstance(node, list):
        return [_bound(item, bound) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "<<bound>>":
            if bound != "<<absent>>":
                out["maxItems"] = bound
            continue
        out[key] = _bound(value, bound)
    return out


def _document(
    shape: Any, ref: str, codes: tuple[str, ...], media: tuple[str, ...], swagger: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A document and the operation to judge in it."""
    schemas_key = "definitions" if swagger else "components"
    document: dict[str, Any] = {"swagger": "2.0"} if swagger else {"openapi": "3.0.3"}
    store: dict[str, Any] = {}
    responses_store: dict[str, Any] = {}

    def schema_ref(name: str) -> str:
        return f"#/definitions/{name}" if swagger else f"#/components/schemas/{name}"

    schema = copy.deepcopy(shape)
    if ref == "a $ref to the schema":
        store["List"] = schema
        schema = {"$ref": schema_ref("List")}
    elif ref == "a chain of $refs":
        store["List"] = schema
        store["Alias"] = {"$ref": schema_ref("List")}
        schema = {"$ref": schema_ref("Alias")}
    elif ref == "a $ref to the array":
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict) and "products" in properties:
            store["Products"] = properties["products"]
            properties["products"] = {"$ref": schema_ref("Products")}
        else:
            store["List"] = schema
            schema = {"$ref": schema_ref("List")}
    elif ref == "a $ref out of the document":
        schema = {"$ref": "other.json#/List"}
    elif ref == "a dangling $ref":
        schema = {"$ref": schema_ref("Missing")}
    elif ref == "a $ref with an escaped token":
        store["a/b~c"] = schema
        name = "a~1b~0c"
        schema = {"$ref": f"#/definitions/{name}" if swagger else f"#/components/schemas/{name}"}

    if swagger:
        response: dict[str, Any] = {"description": "ok", "schema": schema}
    else:
        response = {"description": "ok", "content": {m: {"schema": schema} for m in media}}
    if ref == "a $ref to the response":
        responses_store["Listing"] = response
        response = {"$ref": "#/responses/Listing" if swagger else "#/components/responses/Listing"}
    responses: dict[str, Any] = {}
    for code in codes:
        responses[code] = response if code.startswith("2") else {"description": "no", "content": {}}
    if codes == ("404",):
        responses["404"] = response
    if swagger:
        if store:
            document["definitions"] = store
        if responses_store:
            document["responses"] = responses_store
    else:
        components: dict[str, Any] = {}
        if store:
            components["schemas"] = store
        if responses_store:
            components["responses"] = responses_store
        if components:
            document[schemas_key] = components
    operation = {"responses": responses}
    document["paths"] = {"/products": {"get": operation}}
    return document, operation


def generate() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(name: str, shape_name: str, bound: str, ref: str, codes, media, swagger) -> None:
        shape = _bound(SHAPES[shape_name], BOUNDS[bound])
        document, _ = _document(shape, ref, codes, media, swagger)
        cases.append({"name": name, "document": document, "path": "/products", "method": "get"})

    json_media = ("application/json",)
    for shape in SHAPES:
        for ref in REFS:
            for bound in BOUNDS:
                add(
                    f"oas3 {shape}, {ref}, maxItems {bound}",
                    shape,
                    bound,
                    ref,
                    ("200",),
                    json_media,
                    False,
                )
    for shape in SHAPES:
        for bound in ("absent", "50"):
            for ref in (
                "inline",
                "a $ref to the schema",
                "a $ref to the response",
                "a $ref to the array",
            ):
                add(
                    f"swagger2 {shape}, {ref}, maxItems {bound}",
                    shape,
                    bound,
                    ref,
                    ("200",),
                    (),
                    True,
                )
    statuses: dict[str, tuple[str, ...]] = {
        "201 only": ("201",),
        "2XX only": ("2XX",),
        "2xx only": ("2xx",),
        "200 and 404": ("200", "404"),
        "a list on a non-2xx response only": ("404",),
        "204 and 200": ("204", "200"),
        "no responses": (),
        "a 3-digit code that is not a number": ("2AB",),
    }
    medias: dict[str, tuple[str, ...]] = {
        "problem+json": ("application/problem+json",),
        "json with a charset": ("application/json; charset=utf-8",),
        "upper-case JSON": ("Application/JSON",),
        "text only": ("text/plain",),
        "text and JSON": ("text/plain", "application/json"),
        "no media type": (),
    }
    for shape in ("a top-level array", "an envelope with one array", "an envelope with two arrays"):
        for bound in ("absent", "50"):
            for status, codes in statuses.items():
                add(
                    f"oas3 {shape}, status {status}, maxItems {bound}",
                    shape,
                    bound,
                    "inline",
                    codes,
                    json_media,
                    False,
                )
            for label, media in medias.items():
                add(
                    f"oas3 {shape}, media {label}, maxItems {bound}",
                    shape,
                    bound,
                    "inline",
                    ("200",),
                    media,
                    False,
                )

    # A $ref loop, which must end.
    loop = {
        "openapi": "3.0.3",
        "components": {
            "schemas": {
                "A": {"$ref": "#/components/schemas/B"},
                "B": {"$ref": "#/components/schemas/A"},
            }
        },
        "paths": {
            "/products": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/A"}}
                            }
                        }
                    }
                }
            }
        },
    }
    cases.append({"name": "a $ref loop", "document": loop, "path": "/products", "method": "get"})
    for case in cases:
        operation = case["document"]["paths"][case["path"]][case["method"]]
        found, bound = response_list(case["document"], operation)
        case["expect"] = {"list": found, "max_items": bound}
    return cases


JUDGE_CASES: list[dict[str, Any]] = [
    {"name": "within", "measured": {"items": 3}, "bound": 50},
    {"name": "at the bound", "measured": {"items": 50}, "bound": 50},
    {"name": "one over", "measured": {"items": 51}, "bound": 50},
    {"name": "empty", "measured": {"items": 0}, "bound": 1},
    {"name": "on an envelope, over", "measured": {"items": 7}, "bound": 5, "at": "/products"},
    {"name": "a 404", "measured": {"not_counted": "status", "status": 404}, "bound": 50},
    {"name": "not JSON", "measured": {"not_counted": "not_json"}, "bound": 50},
    {
        "name": "no array at the pointer",
        "measured": {"not_counted": "no_array"},
        "bound": 50,
        "at": "/products",
    },
    {"name": "no array at the top", "measured": {"not_counted": "no_array"}, "bound": 50},
    {"name": "too large", "measured": {"not_counted": "too_large"}, "bound": 50},
    {"name": "counted and not", "measured": {"not_counted": "not_json", "items": 3}, "bound": 50},
    {"name": "an unknown reason", "measured": {"not_counted": "tired"}, "bound": 50},
    {"name": "a negative count", "measured": {"items": -1}, "bound": 50},
    {"name": "a fractional count", "measured": {"items": 1.5}, "bound": 50},
    {"name": "a count that is true", "measured": {"items": True}, "bound": 50},
    {"name": "a bound of zero", "measured": {"items": 0}, "bound": 0},
    {"name": "a bound past the cap", "measured": {"items": 0}, "bound": 1_000_001},
    {
        "name": "another pointer",
        "measured": {"items": 1},
        "bound": 5,
        "at": "/a",
        "expected_at": "/b",
    },
    {
        "name": "a status out of range",
        "measured": {"not_counted": "status", "status": 42},
        "bound": 50,
    },
]


def judge_cases() -> list[dict[str, Any]]:
    out = []
    for case in JUDGE_CASES:
        at = case.get("at", "")
        measured = {"url": "http://shop/products", "method": "GET", "at": at, **case["measured"]}
        expected = {"response_items_max": case["bound"], "at": case.get("expected_at", at)}
        try:
            verdict, reason = judge_response_items(measured, expected)
            record: dict[str, Any] = {"verdict": verdict, "reason": reason}
        except ListShapeError:
            record = {"error": True}
        out.append(
            {"name": case["name"], "measured": measured, "expected": expected, "expect": record}
        )
    return out


def fixture() -> dict[str, Any]:
    return {
        "why": [
            "Phase 38 part 2. Generated by shared/tests/test_lists.py --write. response_list: "
            "what culprit_model.lists.response_list and model.ResponseList make of one "
            "operation of a document: whether it answers a list, and its bound (null: "
            "unbounded). judge: what judge_response_items and model.JudgeResponseItems make "
            "of a probe.http.response_items reading; error when the reading is not the rule's "
            "input."
        ],
        "response_list": generate(),
        "judge": judge_cases(),
    }


def _recorded() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_is_what_the_rule_makes_of_it() -> None:
    assert _recorded() == json.loads(json.dumps(fixture())), (
        "list_conformance.json is stale: "
        "cd api && uv run python ../shared/tests/test_lists.py --write"
    )


def _expect(name: str) -> dict[str, Any]:
    cases = {case["name"]: case["expect"] for case in _recorded()["response_list"]}
    return cases[name]


@pytest.mark.parametrize(
    ("name", "found", "bound"),
    [
        # The brief's cases: top level; an envelope; $ref; maxItems present
        # and absent; two arrays; an array on a non-2xx response only.
        ("oas3 a top-level array, inline, maxItems 50", True, 50),
        ("oas3 a top-level array, inline, maxItems absent", True, None),
        ("oas3 an envelope with one array, a $ref to the schema, maxItems 50", True, 50),
        ("oas3 an envelope with one array, a $ref to the array, maxItems absent", True, None),
        ("oas3 an envelope with one array, a $ref to the response, maxItems 0", True, 0),
        ("oas3 an envelope with two arrays, inline, maxItems 50", False, None),
        (
            "oas3 a top-level array, status a list on a non-2xx response only, maxItems 50",
            False,
            None,
        ),
        ("swagger2 an envelope with one array, a $ref to the schema, maxItems 50", True, 50),
        # A bound that is not a whole number is no bound.
        ("oas3 a top-level array, inline, maxItems 1.5", True, None),
        ('oas3 a top-level array, inline, maxItems the text "50"', True, None),
        ("oas3 a top-level array, inline, maxItems true", True, None),
        ("oas3 a top-level array, inline, maxItems 50.0", True, 50),
        # Not listed: these are LIMITS.
        ("oas3 an optional array (anyOf), inline, maxItems 50", False, None),
        ("oas3 a nullable array (a type list), inline, maxItems 50", False, None),
        ("oas3 a top-level array, a $ref out of the document, maxItems 50", False, None),
        ("oas3 a top-level array, media text only, maxItems 50", False, None),
        ("oas3 a top-level array, media problem+json, maxItems 50", True, 50),
        ("oas3 a top-level array, status 204 and 200, maxItems 50", True, 50),
        ("a $ref loop", False, None),
    ],
)
def test_the_anchors(name: str, found: bool, bound: int | None) -> None:
    assert _expect(name) == {"list": found, "max_items": bound}


def test_the_judge_cases_are_recorded() -> None:
    by_name = {case["name"]: case["expect"] for case in _recorded()["judge"]}
    assert by_name["at the bound"] == {"verdict": "pass", "reason": ""}
    assert by_name["one over"]["verdict"] == "fail"
    assert by_name["a 404"]["verdict"] == "inconclusive"
    assert "404" in by_name["a 404"]["reason"]
    assert "/products" in by_name["no array at the pointer"]["reason"]
    assert by_name["counted and not"] == {"error": True}
    assert by_name["another pointer"] == {"error": True}


@pytest.mark.parametrize(
    ("pointer", "problem"),
    [
        ("/products", False),
        ("/a~0b/c~1d/0", False),
        ("", True),
        ("products", True),
        ("/a~2", True),
        ("/a~", True),
        ("/a\tb", True),
        ("/" + "a" * 255, False),
        ("/" + "a" * 256, True),
    ],
)
def test_the_pointer_rule(pointer: str, problem: bool) -> None:
    assert (json_pointer_problem(pointer) is not None) is problem


if __name__ == "__main__" and "--write" in sys.argv:
    FIXTURE.write_text(json.dumps(fixture(), indent=1) + "\n", encoding="utf-8", newline="\n")
    data = fixture()
    listed = sum(1 for case in data["response_list"] if case["expect"]["list"])
    print(
        f"{len(data['response_list'])} response_list cases ({listed} lists), "
        f"{len(data['judge'])} judge cases"
    )
