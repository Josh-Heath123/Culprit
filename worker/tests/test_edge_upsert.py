"""Unit tests for app.consumer's edge-aggregation step (Phase 19).

Pure-function test only, no DB or Redis — `_aggregate_edge_counts` is
deliberately DB-free (see app/consumer.py's own docstring on it) so
"repeated observations increment rather than duplicate" is testable
without a database, matching every other file in worker/tests/.
"""

from app.consumer import _aggregate_edge_counts


def test_repeated_pair_in_one_batch_aggregates_to_a_single_row() -> None:
    rows = [
        {"from_service": "order-service", "to_service": "inventory-service"},
        {"from_service": "order-service", "to_service": "inventory-service"},
        {"from_service": "order-service", "to_service": "inventory-service"},
    ]
    result = _aggregate_edge_counts(rows)
    assert result == [
        {"from_service": "order-service", "to_service": "inventory-service", "observations": 3}
    ]


def test_distinct_pairs_stay_separate_rows() -> None:
    rows = [
        {"from_service": "order-service", "to_service": "inventory-service"},
        {"from_service": "order-service", "to_service": "payments-service"},
        {"from_service": "order-service", "to_service": "inventory-service"},
    ]
    result = _aggregate_edge_counts(rows)
    by_pair = {(row["from_service"], row["to_service"]): row["observations"] for row in result}
    assert by_pair == {
        ("order-service", "inventory-service"): 2,
        ("order-service", "payments-service"): 1,
    }


def test_direction_matters_reverse_pair_is_distinct() -> None:
    rows = [
        {"from_service": "order-service", "to_service": "inventory-service"},
        {"from_service": "inventory-service", "to_service": "order-service"},
    ]
    result = _aggregate_edge_counts(rows)
    by_pair = {(row["from_service"], row["to_service"]): row["observations"] for row in result}
    assert by_pair == {
        ("order-service", "inventory-service"): 1,
        ("inventory-service", "order-service"): 1,
    }
