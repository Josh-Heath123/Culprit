"""`culprit.yaml`'s `budgets:` on the control-plane side (Phase 36 part 1).

The control plane does not act on budgets — the `culprit` binary turns
them into INTENT facts — but `apply-model` has to accept a manifest that
carries them and `--export` has to give them back. A manifest field the
API's model did not know has broken a fresh clone's quickstart before, so
the demo's own manifest is loaded here. Pure: no database.
"""

import json
from pathlib import Path

import pytest
from app.model.manifest import ManifestError, dump_manifest, load_manifest
from culprit_model.subjects import build

DEMO = Path(__file__).parents[2] / "demo-services" / "culprit.yaml"

#: Built, never hand-formatted (scripts/tests/test_subject_construction.py).
ITEMS = build("http", component="shop", method="GET", path="/items")
READY = build("http", component="inventory-service", method="GET", path="/ready")

BASE = """
version: 1
components:
  - name: shop
budgets:
  - subject: {subject}
    predicate: {predicate}
    value: {value}
    why: the listing page waits on it
"""


def _manifest(predicate: str, value: object) -> str:
    return BASE.format(subject=json.dumps(ITEMS), predicate=predicate, value=value)


def test_the_demo_manifest_with_its_budget_loads_and_round_trips() -> None:
    manifest = load_manifest(DEMO.read_text(encoding="utf-8"))
    assert [(b.subject, b.predicate, b.value) for b in manifest.budgets] == [
        (READY, "latency_p95_ms", 300)
    ]
    exported = dump_manifest(manifest)
    again = load_manifest(exported)
    assert again == manifest
    assert dump_manifest(again) == exported


LITERALS = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "latency_conformance.json").read_text(
        encoding="utf-8"
    )
)["budget_literals"]


def test_the_largest_budget_loads_as_the_go_loader_loads_it() -> None:
    assert load_manifest(_manifest("latency_p95_ms", 60_000)).budgets[0].value == 60_000


@pytest.mark.parametrize("case", LITERALS, ids=lambda case: case["literal"])
def test_a_budget_loads_only_when_written_as_plain_decimal_digits(case: dict) -> None:
    """Phase 36 part 2, from the fixture the Go loader reads too. Part 1
    loaded a whole float (`300.0`); both readers now refuse every form but
    plain decimal digits, because they read `0454`, `1e3`, `0o454` and
    `300_000` as different numbers or as strings."""
    written = case["literal"] if case["plain"] else json.dumps(case["literal"])
    if case["refused"]:
        with pytest.raises(ManifestError, match="budgets") as refused:
            load_manifest(_manifest("latency_p95_ms", written))
        assert case["reason"] in str(refused.value)
    else:
        assert load_manifest(_manifest("latency_p95_ms", written)).budgets[0].value == int(
            case["literal"]
        )


@pytest.mark.parametrize(
    "written", ["!!int 300", "*ms"], ids=["an explicit tag", "an alias"]
)
def test_a_tagged_or_aliased_budget_is_refused(written: str) -> None:
    text = ("x-ms: &ms 300\n" if written == "*ms" else "") + _manifest("latency_p95_ms", written)
    with pytest.raises(ManifestError, match="without quotes, a tag or an alias"):
        load_manifest(text)


def test_two_budgets_for_one_route_and_predicate_are_refused() -> None:
    twice = _manifest("latency_p95_ms", 300) + (
        f"  - subject: {json.dumps(ITEMS)}\n    predicate: latency_p95_ms\n"
        "    value: 900\n    why: the same route again\n"
    )
    with pytest.raises(ManifestError, match="repeats"):
        load_manifest(twice)


@pytest.mark.parametrize("predicate", ["latency_p50_ms", "latency_p95_ms"])
def test_a_known_budget_predicate_loads(predicate: str) -> None:
    manifest = load_manifest(_manifest(predicate, 300))
    assert manifest.budgets[0].predicate == predicate


@pytest.mark.parametrize(
    ("predicate", "value"),
    [
        ("latency_p99_ms", 300),
        ("latency_ms", 300),
        ("latency_p95_ms", 0),
        ("latency_p95_ms", 2.5),
        ("latency_p95_ms", '"fast"'),
        ("latency_p95_ms", 60_001),
        ("latency_p95_ms", 5_000_000_000_000),
    ],
)
def test_a_budget_the_rule_cannot_use_is_refused(predicate: str, value: object) -> None:
    with pytest.raises(ManifestError, match="budgets"):
        load_manifest(_manifest(predicate, value))
