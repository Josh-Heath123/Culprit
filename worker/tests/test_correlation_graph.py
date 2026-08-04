"""Unit tests for the pure correlation graph (app/correlation/graph.py).

Not Hypothesis property tests (not asked for in Phase 5) — these are
direct, deterministic checks of the exact scenarios the live
verification exercises: same/adjacent service within the window links,
non-adjacent services never link on time proximity alone, and
out-of-window pairs never link regardless of service.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.correlation.graph import CORRELATION_WINDOW, AnomalyNode, build_graph, connected_components

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _node(service_name: str, offset: timedelta) -> AnomalyNode:
    return AnomalyNode(id=uuid4(), service_name=service_name, detected_at=T0 + offset)


def test_same_service_within_window_links() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", timedelta(minutes=1))
    components = connected_components(build_graph([a, b]))
    assert components == [{a.id, b.id}]


def test_adjacent_services_within_window_link() -> None:
    order = _node("order-service", timedelta(0))
    inventory = _node("inventory-service", timedelta(minutes=2))
    components = connected_components(build_graph([order, inventory]))
    assert components == [{order.id, inventory.id}]


def test_non_adjacent_services_never_link_on_time_alone() -> None:
    """The actual point of the adjacency rule: inventory-service and
    payments-service are never directly adjacent, so a coincidental
    same-moment anomaly in both must NOT be linked just because they're
    close in time.
    """
    inventory = _node("inventory-service", timedelta(0))
    payments = _node("payments-service", timedelta(seconds=1))
    components = connected_components(build_graph([inventory, payments]))
    expected = {frozenset({inventory.id}), frozenset({payments.id})}
    assert {frozenset(c) for c in components} == expected


def test_bridging_anomaly_joins_all_three_into_one_component() -> None:
    order = _node("order-service", timedelta(minutes=1))
    inventory = _node("inventory-service", timedelta(0))
    payments = _node("payments-service", timedelta(minutes=2))
    components = connected_components(build_graph([inventory, order, payments]))
    assert components == [{inventory.id, order.id, payments.id}]


def test_same_service_outside_window_does_not_link() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", CORRELATION_WINDOW + timedelta(seconds=1))
    components = connected_components(build_graph([a, b]))
    assert {frozenset(c) for c in components} == {frozenset({a.id}), frozenset({b.id})}


def test_exactly_at_window_boundary_links() -> None:
    a = _node("order-service", timedelta(0))
    b = _node("order-service", CORRELATION_WINDOW)
    components = connected_components(build_graph([a, b]))
    assert components == [{a.id, b.id}]
