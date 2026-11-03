"""Phase 31: worker/app/anomaly/job.py emits an impedance reading beside
each score it already wrote an anomaly for.

The attribution rule is the whole risk. A reading is keyed by a
*connection* subject, and a metric row is about a service — so something
has to decide which edge the measurement belongs to. Getting that wrong
is not a missing finding, it is a wrong one: a real measurement filed
against the wrong edge, indistinguishable from a correct one. The rule is
therefore three branches, and the third is "emit nothing".

`scorer.py` and `state.py` are deliberately untouched by this phase, so
nothing here exercises the statistics — only the wiring around them.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.anomaly.job import (
    IMPEDANCE_PROBE_ID,
    IMPEDANCE_PROBE_VERSION,
    _impedance_reading,
    _impedance_target,
    _peer_from_attributes,
    _reading_row,
)
from app.anomaly.scorer import MIN_OBSERVATIONS
from culprit_model.capabilities import Capability
from culprit_model.readings import Reading, Verdict
from culprit_model.subjects import build, parse

KNOWN = {"orders-api", "payments-api", "inventory-api"}
TAKEN_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


# (a) the row names a peer -------------------------------------------------


def test_a_named_peer_attributes_the_reading_to_that_edge() -> None:
    target = _impedance_target(
        "orders-api",
        {"peer.service": "payments-api"},
        KNOWN,
        # A declared upstream exists and is deliberately ignored: what the
        # service itself said it was calling beats what the model declares
        # about who calls it.
        {"orders-api": ("inventory-api",)},
    )
    assert target == build("connection", from_component="orders-api", to_component="payments-api")


def test_every_spelling_of_the_peer_attribute_is_read() -> None:
    for key in ("peer.service", "peer_service", "server.address"):
        target = _impedance_target("orders-api", {key: "payments-api"}, KNOWN, {})
        assert target == build(
            "connection", from_component="orders-api", to_component="payments-api"
        )


def test_an_unknown_peer_name_is_not_a_peer() -> None:
    """An attribute value is whatever the instrumented service put there.
    A subject built from an unregistered name would describe a connection
    that exists in no model — unjoinable, and indistinguishable from a
    typo. Falls through to (b), which here has nothing either."""
    assert _peer_from_attributes({"peer.service": "not-registered"}, KNOWN) is None
    assert _impedance_target("orders-api", {"peer.service": "not-registered"}, KNOWN, {}) is None


def test_attributes_that_are_not_a_mapping_are_ignored() -> None:
    assert _peer_from_attributes(None, KNOWN) is None
    assert _peer_from_attributes(["peer.service"], KNOWN) is None


# (b) exactly one declared inbound connection ------------------------------


def test_one_declared_upstream_attributes_the_reading_to_it() -> None:
    target = _impedance_target("payments-api", {}, KNOWN, {"payments-api": ("orders-api",)})
    assert target == build("connection", from_component="orders-api", to_component="payments-api")


# (c) anything else --------------------------------------------------------


def test_several_declared_upstreams_emit_nothing() -> None:
    """Two callers, no evidence which one this metric is about. A guess
    here would be a measurement filed against an edge it did not come
    from."""
    inbound = {"payments-api": ("orders-api", "inventory-api")}
    assert _impedance_target("payments-api", {}, KNOWN, inbound) is None


def test_no_declared_upstream_emits_nothing() -> None:
    assert _impedance_target("payments-api", {}, KNOWN, {}) is None
    assert _impedance_target("payments-api", {}, KNOWN, {"orders-api": ("x",)}) is None


# the reading itself -------------------------------------------------------


def test_the_verdict_follows_the_same_threshold_the_anomaly_row_does() -> None:
    edge = build("connection", from_component="orders-api", to_component="payments-api")
    assert (
        _impedance_reading(edge, "http.server.duration", 0.5, 120, TAKEN_AT).verdict
        is Verdict.PASS
    )
    assert (
        _impedance_reading(edge, "http.server.duration", 4.2, 120, TAKEN_AT).verdict
        is Verdict.FAIL
    )


def test_a_warming_up_baseline_is_inconclusive_with_a_reason() -> None:
    """`.claude/rules/model.md`: a probe that cannot admit uncertainty is
    a probe that guesses. Dropping the reading instead would make "not
    measurable yet" and "measured, nothing unusual" indistinguishable in
    the OBSERVED plane — and `Reading` refuses an unexplained
    inconclusive, so the reason is not optional."""
    edge = build("connection", from_component="orders-api", to_component="payments-api")
    reading = _impedance_reading(edge, "http.server.duration", None, 12, TAKEN_AT)

    assert reading.verdict is Verdict.INCONCLUSIVE
    assert reading.reason is not None
    assert "12" in reading.reason and str(MIN_OBSERVATIONS) in reading.reason
    assert reading.measured["deviation"] is None


def test_the_reading_names_its_probe_its_grant_and_its_sample_count() -> None:
    edge = build("connection", from_component="orders-api", to_component="payments-api")
    reading = _impedance_reading(edge, "http.server.duration", 4.2, 120, TAKEN_AT)

    assert reading.probe_id == IMPEDANCE_PROBE_ID
    assert reading.agent_id == "culprit-worker"
    assert reading.grants_used == (Capability.TELEMETRY_METRICS_READ,)
    # A z-score is meaningless without knowing how long the baseline has
    # been accumulating.
    assert reading.measured == {
        "metric": "http.server.duration",
        "deviation": 4.2,
        "samples": 120,
    }
    # Built, never hand-formatted (.claude/rules/model.md).
    kind, parts = parse(reading.target)
    assert kind == "connection"
    assert parts == {"from_component": "orders-api", "to_component": "payments-api"}


def test_the_row_carries_no_evidence_and_no_expectation() -> None:
    """Impedance has no expectation plane: "usual" is a statistic over
    OBSERVED, never a claim about what is correct. And nothing from a
    metric row's attributes reaches the reading — the peer name is read
    to pick a subject and then dropped."""
    edge = build("connection", from_component="orders-api", to_component="payments-api")
    row = _reading_row(_impedance_reading(edge, "http.server.duration", 4.2, 120, TAKEN_AT))

    assert row["expected"] is None
    assert row["expected_source"] is None
    assert row["evidence"] == []
    assert row["reason"] is None
    assert row["grants_used"] == ["telemetry.metrics.read"]
    assert row["taken_at"] == TAKEN_AT


# volume: one reading per connection-metric per batch ----------------------


def test_a_batch_collapses_to_the_latest_reading_per_connection_and_metric() -> None:
    """A reading answers "what is this connection's impedance now".

    The scorer's state is cumulative, so 2000 rows of one metric are 2000
    restatements of one measurement, not 2000 measurements. Writing all of
    them would put the raw metric event rate into a 90-day hypertable
    while `anomalies` — which only gains a row when something is actually
    wrong — stays small. This asserts the collapse, and that the surviving
    reading is the *last* one scored rather than an arbitrary one.
    """
    target = build("connection", from_component="orders-api", to_component="payments-api")

    latest: dict[tuple[str, str], Reading] = {}
    for index in range(50):
        reading = _impedance_reading(
            target=target,
            metric_name="latency_ms",
            deviation=float(index),
            samples=MIN_OBSERVATIONS + index,
            taken_at=TAKEN_AT,
        )
        latest[(target, "latency_ms")] = reading

    assert len(latest) == 1, "fifty rows of one metric became more than one reading"
    surviving = latest[(target, "latency_ms")]
    assert surviving.measured["deviation"] == 49.0, "the last row scored did not win"


def test_two_metrics_on_one_connection_stay_two_readings() -> None:
    """The collapse is per (connection, metric), not per connection —
    latency and error rate are different measurements of the same edge and
    losing one would hide half the picture."""
    target = build("connection", from_component="orders-api", to_component="payments-api")

    latest: dict[tuple[str, str], Reading] = {}
    for metric in ("latency_ms", "error_rate"):
        latest[(target, metric)] = _impedance_reading(
            target=target,
            metric_name=metric,
            deviation=1.0,
            samples=MIN_OBSERVATIONS,
            taken_at=TAKEN_AT,
        )

    assert len(latest) == 2


def test_the_worker_stamps_the_same_probe_version_the_catalogue_declares() -> None:
    """The worker writes readings for a probe whose manifest lives in Go.

    `IMPEDANCE_PROBE_ID` / `IMPEDANCE_PROBE_VERSION` mirror
    `cli/internal/probe/observe_probes.go`'s manifest, and nothing held
    them together — so bumping the Go manifest to version 2 would leave
    the worker silently stamping version 1 on readings that are no longer
    that probe's, which is a silent-wrong-answer failure mode rather than
    a build break. Named by the Phase 31 invariant audit.

    Checked against `api/app/readings/catalogue.json`, which
    `api/tests/test_probes_api.py` already holds to the Go source — so
    the chain worker -> catalogue -> Go is closed at both links.
    """
    catalogue = json.loads(
        (
            Path(__file__).resolve().parents[2] / "api" / "app" / "readings" / "catalogue.json"
        ).read_text(encoding="utf-8")
    )
    manifests = {entry["id"]: entry for entry in catalogue}

    assert IMPEDANCE_PROBE_ID in manifests, (
        f"{IMPEDANCE_PROBE_ID} is not in the probe catalogue; the worker is "
        "writing readings for a probe that does not exist"
    )
    assert manifests[IMPEDANCE_PROBE_ID]["version"] == IMPEDANCE_PROBE_VERSION, (
        f"the catalogue declares {IMPEDANCE_PROBE_ID} at version "
        f"{manifests[IMPEDANCE_PROBE_ID]['version']} but the worker stamps "
        f"{IMPEDANCE_PROBE_VERSION}. Bump both, or readings will claim to "
        "come from a probe version that never produced them."
    )
