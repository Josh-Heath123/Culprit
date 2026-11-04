"""Phase 27 field 13: graph tests for request-path derivation on a
branching topology.

The fixture below is deliberately not the demo's three-service triangle.
A triangle cannot distinguish "ordered by hop distance" from "ordered
alphabetically", and it has no background edge, no second connection
kind between the same pair, and no diamond — every one of which is a
case `upstream_connections` has to get right before Phase 29 computes
divergence severity from its output.

    checkout-web ──http──▶ orders-svc ──http──▶ payments-svc ──http──▶ stripe
                                │  │                   │
                                │  └──sql──▶ orders-db │
                                │                      │
                                └──http──▶ inventory-svc
                                │
                                └──message──▶ nightly-recon   (background)

`payments-svc` and `inventory-svc` both hang off `orders-svc` (the
branch); `orders-svc` also reaches `orders-db` over SQL rather than HTTP
(two kinds in one graph); `nightly-recon` is reachable but off the
request path.
"""

import pytest
from culprit_model.graph import (
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    Criticality,
    SystemGraph,
    UnknownComponent,
)
from culprit_model.subjects import SubjectKind
from culprit_model.subjects import build as build_subject
from pydantic import ValidationError


def _component(name: str, kind: ComponentKind = ComponentKind.SERVICE, **kwargs) -> Component:
    return Component(name=name, kind=kind, **kwargs)


def _connection(
    source: str,
    target: str,
    kind: ConnectionKind = ConnectionKind.HTTP,
    criticality: Criticality = Criticality.UNKNOWN,
) -> Connection:
    return Connection(
        from_component=source, to_component=target, kind=kind, criticality=criticality
    )


@pytest.fixture
def branching() -> SystemGraph:
    return SystemGraph(
        components=(
            _component("checkout-web", ComponentKind.FRONTEND),
            _component("orders-svc"),
            _component("payments-svc"),
            _component("inventory-svc"),
            _component("orders-db", ComponentKind.DATABASE),
            _component("stripe", ComponentKind.EXTERNAL_API),
            _component("nightly-recon", ComponentKind.JOB),
        ),
        connections=(
            _connection("checkout-web", "orders-svc", criticality=Criticality.ON_REQUEST_PATH),
            _connection("orders-svc", "payments-svc", criticality=Criticality.ON_REQUEST_PATH),
            _connection("orders-svc", "inventory-svc", criticality=Criticality.ON_REQUEST_PATH),
            _connection("orders-svc", "orders-db", ConnectionKind.SQL, Criticality.ON_REQUEST_PATH),
            _connection("payments-svc", "stripe", criticality=Criticality.ON_REQUEST_PATH),
            _connection(
                "orders-svc",
                "nightly-recon",
                ConnectionKind.MESSAGE,
                Criticality.BACKGROUND,
            ),
        ),
    )


# --- request-path derivation (acceptance criterion 4) -----------------


def test_upstream_connections_are_ordered_nearest_hop_first(branching: SystemGraph) -> None:
    path = branching.upstream_connections("orders-svc")
    assert [(c.from_component, c.to_component, str(c.kind)) for c in path] == [
        # hop 1, sorted within the hop
        ("orders-svc", "inventory-svc", "http"),
        ("orders-svc", "orders-db", "sql"),
        ("orders-svc", "payments-svc", "http"),
        # hop 2
        ("payments-svc", "stripe", "http"),
    ]


def test_upstream_connections_from_the_frontend_include_the_whole_chain(
    branching: SystemGraph,
) -> None:
    path = branching.upstream_connections("checkout-web")
    assert path[0].from_component == "checkout-web"
    assert ("payments-svc", "stripe") in {(c.from_component, c.to_component) for c in path}


def test_background_connections_are_off_the_request_path(branching: SystemGraph) -> None:
    """A nightly reconciliation job is reachable but is not on the path a
    failing request took."""
    path = branching.upstream_connections("orders-svc")
    assert "nightly-recon" not in {c.to_component for c in path}
    # ...but it is still part of the model, and still reachable.
    assert "nightly-recon" in branching.reachable_from("orders-svc")


def test_unknown_criticality_stays_on_the_path() -> None:
    """The `Criticality.UNKNOWN` docstring's promise, asserted: an
    unclassified edge is included, because excluding it would hide the
    real cause on any topology nobody had finished labelling."""
    graph = SystemGraph(
        components=(_component("a"), _component("b")),
        connections=(_connection("a", "b", criticality=Criticality.UNKNOWN),),
    )
    assert [c.to_component for c in graph.upstream_connections("a")] == ["b"]


def test_two_kinds_between_the_same_pair_are_two_connections() -> None:
    """Phase 27 field 8: `(from, to, kind)` is the identity, so an HTTP
    link and a shared cache between the same pair are two edges, not a
    duplicate."""
    graph = SystemGraph(
        components=(_component("a"), _component("b")),
        connections=(
            _connection("a", "b", ConnectionKind.HTTP),
            _connection("a", "b", ConnectionKind.CACHE),
        ),
    )
    assert len(graph.upstream_connections("a")) == 2
    assert len({c.key for c in graph.connections}) == 2


def test_a_cycle_terminates() -> None:
    """`service_dependencies` stored both directions of every declared
    pair, so the migrated data is full of two-cycles. Traversal must
    terminate on them, and must not emit the same edge twice."""
    graph = SystemGraph(
        components=(_component("a"), _component("b"), _component("c")),
        connections=(
            _connection("a", "b"),
            _connection("b", "a"),
            _connection("b", "c"),
            _connection("c", "a"),
        ),
    )
    path = graph.upstream_connections("a")
    assert len(path) == len({c.key for c in path}) == 4
    assert graph.reachable_from("a") == ("a", "b", "c")


# --- reachability -----------------------------------------------------


def test_reaches_is_the_mirror_of_reachable_from(branching: SystemGraph) -> None:
    assert branching.reaches("stripe") == ("checkout-web", "orders-svc", "payments-svc")
    assert "stripe" in branching.reachable_from("checkout-web")


def test_reachable_from_excludes_self_without_a_cycle(branching: SystemGraph) -> None:
    assert "checkout-web" not in branching.reachable_from("checkout-web")


# --- refusals rather than empty answers -------------------------------


def test_unknown_component_raises_rather_than_returning_an_empty_path(
    branching: SystemGraph,
) -> None:
    with pytest.raises(UnknownComponent):
        branching.upstream_connections("orders-service")  # not the registered name


def test_a_connection_to_an_unmodelled_component_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not present as components"):
        SystemGraph(
            components=(_component("a"),),
            connections=(_connection("a", "ghost"),),
        )


def test_a_self_loop_is_rejected() -> None:
    with pytest.raises(ValidationError, match="loop back"):
        Connection(from_component="a", to_component="a")


# --- canonicalisation and subjects ------------------------------------


def test_names_are_canonicalised_on_the_way_in() -> None:
    graph = SystemGraph(
        components=(_component("  Orders-SVC "),),
        connections=(),
    )
    assert graph.components[0].name == "orders-svc"
    assert graph.component("ORDERS-SVC").name == "orders-svc"


def test_subjects_are_built_not_formatted() -> None:
    component = _component("orders-svc")
    connection = _connection("orders-svc", "payments-svc")
    assert component.subject == build_subject(SubjectKind.COMPONENT, name="orders-svc")
    assert connection.subject == build_subject(
        SubjectKind.CONNECTION, from_component="orders-svc", to_component="payments-svc"
    )


# --- environment scoping ----------------------------------------------


def test_scoped_to_drops_components_and_their_edges() -> None:
    graph = SystemGraph(
        components=(
            _component("a"),
            _component("b", environment_scope=("staging",)),
        ),
        connections=(_connection("a", "b"),),
    )
    assert {c.name for c in graph.scoped_to("staging").components} == {"a", "b"}
    production = graph.scoped_to("production")
    assert {c.name for c in production.components} == {"a"}
    assert production.connections == ()


def test_an_unscoped_component_exists_everywhere() -> None:
    assert _component("a").exists_in("anywhere")


def test_connection_kinds_match_the_shared_fixture():
    """Phase 32.1: the closed set is one set in both languages, held by
    shared/tests/connection_kind_conformance.json."""
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "connection_kind_conformance.json").read_text(encoding="utf-8")
    )
    assert [kind.value for kind in ConnectionKind] == fixture["kinds"]
    assert Connection.model_fields["kind"].default == ConnectionKind(fixture["default"])
    for refused in fixture["refused"]:
        with pytest.raises(ValueError):
            ConnectionKind(refused)
