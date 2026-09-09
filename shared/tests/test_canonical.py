"""Table-driven tests for canonicalisation (§2.3, Phase 26 field 13).

Path templating is called out in the plan as "the single highest-risk
piece of code in the extraction layer", so the table below is deliberately
exhaustive about the *conventions* rather than about the routes: one row
per way a framework can spell a parameter, plus the cases where an
earlier version of this code was wrong.

Phase 28: the table is now a **shared fixture**, `canonical_conformance.json`,
read here and by `cli/internal/model/canonical_test.go`. §2.3 requires
two sources describing the same thing to produce byte-identical subjects,
and from this phase there are two *implementations* of the normaliser
that decides that — one per language. Holding them to one table is the
only way the requirement stays true; two tables written separately agree
on whatever they both happened to do. `PATH_CASES` below is loaded from
the fixture rather than restated, so a case added to one side is a case
added to both.
"""

import json
from pathlib import Path

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

CONFORMANCE = json.loads(
    (Path(__file__).parent / "canonical_conformance.json").read_text(encoding="utf-8")
)

#: (source path, canonical, which convention it came from)
PATH_CASES = [
    (case["source"], case["canonical"], case["convention"]) for case in CONFORMANCE["path"]
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


@pytest.mark.parametrize(
    ("group", "function"),
    [
        ("method", canonical_method),
        ("component", canonical_component),
        ("identifier", canonical_identifier),
    ],
)
def test_canonical_scalars_match_the_shared_fixture(group: str, function: object) -> None:
    """The non-path canonicalisers, from the same fixture the Go side reads.

    Less risky than path templating, but they feed the same subject URIs,
    so a Go/Python disagreement on `" post "` is just as invisible and
    just as fatal to comparison as one on `/orders/{id}`.
    """
    for case in CONFORMANCE[group]:
        assert function(case["source"]) == case["canonical"], case["convention"]  # type: ignore[operator]


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
