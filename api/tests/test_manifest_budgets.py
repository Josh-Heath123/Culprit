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
PRODUCTS = build("schema", database="inventory-db", namespace="public", table="products")

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
        (READY, "latency_p95_ms", 300),
        (PRODUCTS, "query_mean_ms_max", 20),
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


@pytest.mark.parametrize("written", ["!!int 300", "*ms"], ids=["an explicit tag", "an alias"])
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


@pytest.mark.parametrize(
    "secret", ["postgres://u:hunter2@db/x", "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"]
)
def test_a_credential_pasted_as_a_budget_is_never_echoed(secret: str) -> None:
    """Invariant 7: error text is output. A value written where a budget
    goes is refused as a credential by the scan that runs first, and the
    literal never appears in the error (the Phase 36 part 2 invariant
    audit: it did)."""
    with pytest.raises(ManifestError) as refused:
        load_manifest(_manifest("latency_p95_ms", secret))
    assert secret not in str(refused.value)
    assert "hunter2" not in str(refused.value)


ENTRIES = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "latency_conformance.json").read_text(
        encoding="utf-8"
    )
)["budget_entries"]


@pytest.mark.parametrize("case", ENTRIES, ids=lambda case: case["why"])
def test_a_budget_entry_with_a_merge_key_is_refused(case: dict) -> None:
    """The shared fixture's budget_entries, which the Go loader is held to
    too: a merge key brings a value in past the form check."""
    text = f"version: 1\ncomponents:\n  - name: shop\nbudgets:\n{case['entry']}"
    with pytest.raises(ManifestError) as refused:
        load_manifest(text)
    assert case["reason"] in str(refused.value)


MANIFESTS = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "latency_conformance.json").read_text(
        encoding="utf-8"
    )
)["budget_manifests"]


@pytest.mark.parametrize("case", MANIFESTS, ids=lambda case: case["why"])
def test_the_two_readers_read_budget_manifests_alike(case: dict) -> None:
    """The shared fixture's budget_manifests, which the Go loader reads too:
    each is refused, or loads with the value the Go loader loads."""
    if "loads" in case:
        assert load_manifest(case["manifest"]).budgets[0].value == case["loads"]
        return
    with pytest.raises(ManifestError) as refused:
        load_manifest(case["manifest"])
    if case["reason"] is not None:
        assert case["reason"] in str(refused.value)


KEYS = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "manifest_keys.json").read_text(
        encoding="utf-8"
    )
)["keys"]


def test_the_api_knows_every_top_level_key_the_go_loader_does() -> None:
    """Phase 37 part 1: shared/tests/manifest_keys.json is every top-level
    key of culprit.yaml, and cli/internal/extract's test holds the Go loader
    to it too. A key one reader knows and the other does not fails here."""
    from app.model.manifest import Manifest

    assert sorted(Manifest.model_fields) == sorted(KEYS)


ISOLATION = """
version: 1
components:
  - name: shop
environments:
  local: {adapter: process, components: {shop: {}}}
isolation:
  max_probes: 30
  max_wall_clock: 4m
  environments: {local: {max_probes: 10}}
probes:
  probe.http.latency: {timeout_ms: 90000, environments: [local]}
  probe.net.dns_resolve: {enabled: false, reason: no resolver in this environment}
"""


def test_isolation_and_probes_load_and_round_trip() -> None:
    manifest = load_manifest(ISOLATION)
    assert manifest.isolation is not None and manifest.isolation.max_wall_clock == "4m"
    assert manifest.probes is not None and manifest.probes["probe.http.latency"].timeout_ms == 90000
    exported = dump_manifest(manifest)
    assert load_manifest(exported) == manifest


@pytest.mark.parametrize(
    "broken",
    [
        ISOLATION.replace("4m", "four minutes"),
        ISOLATION.replace("4m", "0s"),
        ISOLATION.replace("max_probes: 30", "max_probes: -1"),
        ISOLATION.replace("{local: {max_probes: 10}}", "{staging: {max_probes: 10}}"),
        ISOLATION.replace("environments: [local]", "environments: [staging]"),
        ISOLATION.replace(
            "enabled: false, reason: no resolver in this environment", "enabled: false"
        ),
        ISOLATION.replace("timeout_ms: 90000", "timeout_ms: 300001"),
    ],
)
def test_isolation_and_probes_are_refused_as_the_go_loader_refuses_them(broken: str) -> None:
    with pytest.raises(ManifestError):
        load_manifest(broken)


SCALARS = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "manifest_scalar_conformance.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("case", SCALARS, ids=lambda case: case["why"])
def test_the_api_reads_culprit_yaml_as_the_go_loader_does(case: dict) -> None:
    """Phase 37 part 1 close-out: one schema for both readers, from the
    fixture the Go loader is held to too."""
    if "refused" in case:
        with pytest.raises(ManifestError) as refused:
            load_manifest(case["manifest"])
        if case["refused"]:
            assert case["refused"] in str(refused.value)
        return
    manifest = load_manifest(case["manifest"])
    if "budget_why" in case:
        assert manifest.budgets[0].why == case["budget_why"]
    if "max_probes" in case:
        assert manifest.isolation is not None
        assert manifest.isolation.max_probes == case["max_probes"]


@pytest.mark.parametrize(
    "tagged",
    [
        "!!python/object/apply:os.system ['echo unsafe']",
        "!!python/object/new:dict {}",
        "!!python/name:os.system",
        "!!timestamp 2026-11-12",
    ],
)
def test_a_tag_that_is_not_plain_data_is_refused(tagged: str) -> None:
    """CodeQL py/unsafe-deserialization on the close-out pull request: the
    manifest is composed and built as plain data, so no tag constructs an
    object, whatever is ever registered on a loader."""
    with pytest.raises(ManifestError, match="not plain data"):
        load_manifest(
            f"version: 1\ninvariants:\n  - subject: s\n    predicate: p\n    value: {tagged}\n"
        )


def test_the_manifest_loader_never_hands_pyyaml_a_document_to_construct() -> None:
    """The structural half: nothing in manifest.py calls a PyYAML entry
    point that constructs objects, or registers a constructor."""
    import ast

    import app.model.manifest as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    banned = {
        "load",
        "load_all",
        "full_load",
        "unsafe_load",
        "safe_load",
        "add_constructor",
        "add_multi_constructor",
        "construct_document",
    }
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in banned
    ]
    assert calls == []
