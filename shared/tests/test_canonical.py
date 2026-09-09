"""Table-driven tests for canonicalisation (§2.3, Phase 26 field 13).

Path templating is called out in the plan as "the single highest-risk
piece of code in the extraction layer", so the table below is deliberately
exhaustive about the *conventions* rather than about the routes: one row
per way a framework can spell a parameter, plus the cases where an
earlier version of this code was wrong.
"""

import pytest
from culprit_model import (
    canonical_component,
    canonical_identifier,
    canonical_json,
    canonical_method,
    canonical_path,
    canonical_value,
    values_equal,
)

PATH_CASES = [
    # (source path, canonical, which convention it came from)
    ("/api/v1/orders", "/api/v1/orders", "literal"),
    ("/", "/", "root"),
    ("", "/", "empty"),
    ("orders", "/orders", "missing leading slash"),
    ("/orders/", "/orders", "trailing slash"),
    ("//api//v1//orders//", "/api/v1/orders", "duplicate slashes"),
    ("  /orders  ", "/orders", "surrounding whitespace"),
    ("/orders/{id}", "/orders/{}", "OpenAPI / FastAPI"),
    ("/orders/{order_id}", "/orders/{}", "OpenAPI, different param name"),
    ("/files/{file_path:path}", "/files/{}", "Starlette path converter"),
    ("/orders/:id", "/orders/{}", "Express"),
    ("/orders/:orderId", "/orders/{}", "Express, camelCase param"),
    (r"/orders/:id(\d+)", "/orders/{}", "Express with inline regex"),
    ("/orders/:id?", "/orders/{}", "Express optional parameter"),
    ("/orders/<id>", "/orders/{}", "Flask, untyped"),
    ("/orders/<int:id>", "/orders/{}", "Flask, typed converter"),
    ("/static/<path:subpath>", "/static/{}", "Flask path converter"),
    ("/orders/<int:pk>/items/<int:item>", "/orders/{}/items/{}", "Django path()"),
    (r"^orders/(?P<pk>[0-9]+)/$", "/orders/{}", "Django re_path, anchored"),
    (
        r"^orders/(?P<pk>\d+)/items/(?P<item>\d+)$",
        "/orders/{}/items/{}",
        "Django re_path, two groups",
    ),
    ("/files/{name}.json", "/files/{}.json", "parameter inside a literal segment"),
    ("/v1/item-:id", "/v1/item-{}", "Express parameter inside a literal segment"),
    ("/*", "/{}", "wildcard"),
    ("/orders?limit=50", "/orders", "query string dropped"),
    ("/orders#anchor", "/orders", "fragment dropped — it is the subject aspect separator"),
    ("/orders?next=/x/y", "/orders", "query string containing a slash"),
]


@pytest.mark.parametrize(
    ("source", "expected", "convention"),
    PATH_CASES,
    ids=[case[2] for case in PATH_CASES],
)
def test_canonical_path(source: str, expected: str, convention: str) -> None:
    assert canonical_path(source) == expected


@pytest.mark.parametrize(
    ("source", "expected", "convention"),
    PATH_CASES,
    ids=[case[2] for case in PATH_CASES],
)
def test_canonical_path_is_idempotent(source: str, expected: str, convention: str) -> None:
    """Applying it twice must not change the answer.

    Not academic: subjects get rebuilt from parsed ones (see
    `subjects.parse`), so a non-idempotent normaliser would make a
    round-tripped subject stop matching the original.
    """
    assert canonical_path(canonical_path(source)) == expected


def test_parameter_names_are_erased_not_preserved() -> None:
    """The deliberate trade-off, pinned so it can't be "fixed" by accident.

    Django calling its capture `pk` and OpenAPI calling it `id` describes
    the same route; keeping the name would mean the two never compare.
    """
    assert canonical_path("/orders/{id}") == canonical_path("/orders/{pk}")


def test_concrete_paths_are_not_treated_as_parameters() -> None:
    """`/orders/12345` stays literal.

    Inferring that a numeric segment "is an id" is how `/orders/count`
    silently becomes `/orders/{}` and two different routes merge. Observed
    traffic needs a route template from the server, not a guess from a URL
    — see docs/LIMITS.md.
    """
    assert canonical_path("/orders/12345") == "/orders/12345"
    assert canonical_path("/orders/count") == "/orders/count"


def test_canonical_method_and_names() -> None:
    assert canonical_method(" post ") == "POST"
    assert canonical_component(" Orders-SVC ") == "orders-svc"
    assert canonical_identifier(" Total_Cents ") == "total_cents"


def test_canonical_component_does_not_fold_separators() -> None:
    """`order_service` and `order-service` stay distinct.

    They genuinely are two different names in this repo (a demo-services
    directory vs. its registered service name); merging them here would
    hide a real naming divergence rather than surface it.
    """
    assert canonical_component("order_service") != canonical_component("order-service")


def test_canonical_value_orders_mappings_and_sets_but_not_lists() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert canonical_value({"tags"}) == ["tags"]
    assert canonical_value(["b", "a"]) == ["b", "a"]
    # Order in a list is meaningful (middleware order, path segments) —
    # sorting it would erase a real divergence.
    assert not values_equal(["b", "a"], ["a", "b"])


def test_canonical_value_is_recursive() -> None:
    left = {"paths": {"b": [1, {"y": 2, "x": 1}], "a": 0}}
    right = {"a": 0, "paths": {"a": 0, "b": [1, {"x": 1, "y": 2}]}}
    assert values_equal(left["paths"], right["paths"])
