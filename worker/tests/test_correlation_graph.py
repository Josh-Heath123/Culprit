"""Unit tests for the pure correlation graph (app/correlation/graph.py).

Not Hypothesis property tests (not asked for in Phase 5) — these are
direct, deterministic checks of the exact scenarios the live
verification exercises: same/adjacent service within the window links,
non-adjacent services never link on time proximity alone, and
out-of-window pairs never link regardless of service.

Phase 14: build_graph() takes adjacency as a parameter now (loaded from
the services/service_dependencies tables by
app/correlation/job.py in production) instead of importing a hardcoded
dict — ADJACENCY below is a fixture matching the old demo topology's
shape, not a reintroduced hardcoded dependency of graph.py itself.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.correlation.graph import CORRELATION_WINDOW, AnomalyNode, build_graph, connected_components

T0 = datetime(2026, 1, 1, tzinfo=UTC)

#: order-service <-> inventory-service and order-service <-> payments-service
#: only — inventory-service and payments-service are deliberately NOT
#: adjacent to each other, matching the demo topology's real shape and
#: giving test_non_adjacent_services_never_link_on_time_alone a genuine
#: non-adjacent pair to assert against.
ADJACENCY = {
    "order-service": frozenset({"inventory-service", "payments-service"}),
    "inventory-service": frozenset({"order-service"}),
    "payments-service": frozenset({"order-service"}),
}


def _node(service_name: str, offset: timedelta) -> AnomalyNode:
    return AnomalyNode(id=uuid4(), service_name=service_name, detected_at=T0 + offset)


def test_same_service_within_window_links() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", timedelta(minutes=1))
    components = connected_components(build_graph([a, b], ADJACENCY))
    assert components == [{a.id, b.id}]


def test_adjacent_services_within_window_link() -> None:
    order = _node("order-service", timedelta(0))
    inventory = _node("inventory-service", timedelta(minutes=2))
    components = connected_components(build_graph([order, inventory], ADJACENCY))
    assert components == [{order.id, inventory.id}]


def test_non_adjacent_services_never_link_on_time_alone() -> None:
    """The actual point of the adjacency rule: inventory-service and
    payments-service are never directly adjacent, so a coincidental
    same-moment anomaly in both must NOT be linked just because they're
    close in time.
    """
    inventory = _node("inventory-service", timedelta(0))
    payments = _node("payments-service", timedelta(seconds=1))
    components = connected_components(build_graph([inventory, payments], ADJACENCY))
    expected = {frozenset({inventory.id}), frozenset({payments.id})}
    assert {frozenset(c) for c in components} == expected


def test_services_absent_from_adjacency_never_link() -> None:
    """The parameterized case the old hardcoded-dict version couldn't
    exercise: two services that simply aren't in the adjacency mapping
    at all (e.g. neither one has been declared adjacent to anything)
    must not correlate on time proximity alone either — same assertion
    as the non-adjacent case above, but against an empty adjacency
    rather than one that just doesn't happen to connect this pair.
    """
    a = _node("checkout-api", timedelta(0))
    b = _node("billing-api", timedelta(seconds=1))
    components = connected_components(build_graph([a, b], {}))
    assert {frozenset(c) for c in components} == {frozenset({a.id}), frozenset({b.id})}


def test_bridging_anomaly_joins_all_three_into_one_component() -> None:
    order = _node("order-service", timedelta(minutes=1))
    inventory = _node("inventory-service", timedelta(0))
    payments = _node("payments-service", timedelta(minutes=2))
    components = connected_components(build_graph([inventory, order, payments], ADJACENCY))
    assert components == [{inventory.id, order.id, payments.id}]


def test_same_service_outside_window_does_not_link() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", CORRELATION_WINDOW + timedelta(seconds=1))
    components = connected_components(build_graph([a, b], ADJACENCY))
    assert {frozenset(c) for c in components} == {frozenset({a.id}), frozenset({b.id})}


def test_exactly_at_window_boundary_links() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", CORRELATION_WINDOW)
    components = connected_components(build_graph([a, b], ADJACENCY))
    assert components == [{a.id, b.id}]
