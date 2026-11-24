# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""Phase 26 regression test: one bad stream entry must not wedge the drain.

The defect: `_drain_batch` parsed a whole batch in a list comprehension.
A single malformed entry raised, the batch was never acked, and the same
batch was reclaimed and failed identically on every subsequent tick —
permanently, silently, with every valid message behind it stuck too.

These use a fake Redis client rather than a container: the behaviour
under test is entirely about which entries end up written, acked and
quarantined, and a real Redis would only make that harder to observe.
"""

import json

import pytest
from app.consumer import DEAD_LETTER_STREAM, _drain_batch, _parse_raw_event

# worker's pytest-asyncio runs in strict mode (see test_embed_job.py) —
# every async test in this file needs the marker.
pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Just enough of redis.asyncio for `_drain_batch`."""

    def __init__(self, entries: list[tuple[str, dict]]) -> None:
        self._entries = entries
        self.acked: list[str] = []
        self.dead_lettered: list[dict] = []

    async def xreadgroup(self, *, groupname, consumername, streams, count, block):
        entries, self._entries = self._entries, []
        return [("stream", entries)] if entries else []

    async def xack(self, stream, group, *entry_ids):
        self.acked.extend(entry_ids)

    async def xadd(self, stream, fields, maxlen=None, approximate=None):
        assert stream == DEAD_LETTER_STREAM
        self.dead_lettered.append(fields)


class RecordingWriter:
    def __init__(self) -> None:
        self.written: list[dict] = []

    async def __call__(self, engine, rows: list[dict]) -> None:
        self.written.extend(rows)


def _valid_entry(entry_id: str, service: str) -> tuple[str, dict]:
    payload = {
        "time": "2026-09-09T10:00:00+00:00",
        "service_name": service,
        "event_type": "metric",
        "metric_name": "request_latency_ms",
        "value": 12.5,
        "attributes": {},
    }
    return entry_id, {"data": json.dumps(payload)}


async def _drain(client: FakeRedis, write: RecordingWriter):
    return await _drain_batch(
        client,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
        stream="otel-metrics",
        group="raw-events-drain",
        start_id=">",
        parse=_parse_raw_event,
        write=write,
    )


@pytest.mark.parametrize(
    ("label", "bad_fields"),
    [
        ("not json at all", {"data": "{definitely not json"}),
        ("json, wrong shape", {"data": json.dumps({"nope": 1})}),
        ("no data field", {}),
        ("event_type outside the allowed set", {"data": json.dumps({
            "time": "2026-09-09T10:00:00+00:00",
            "service_name": "order-service",
            "event_type": "trace",
        })}),
    ],
)
async def test_a_malformed_entry_is_quarantined_and_acked(label: str, bad_fields: dict) -> None:
    client = FakeRedis([_valid_entry("1-0", "order-service"), ("2-0", bad_fields)])
    write = RecordingWriter()

    result = await _drain(client, write)

    # The good entry still got written...
    assert result.written == 1
    assert result.quarantined == 1
    assert [row["service_name"] for row in write.written] == ["order-service"]
    # ...both entries were acked, so neither comes back on the next tick...
    assert client.acked == ["1-0", "2-0"]
    # ...and the bad one is inspectable instead of lost.
    assert len(client.dead_lettered) == 1
    quarantined = client.dead_lettered[0]
    assert quarantined["source_stream"] == "otel-metrics"
    assert quarantined["source_entry_id"] == "2-0"
    assert quarantined["error"]


async def test_a_wholly_unparseable_batch_raises_instead_of_acking() -> None:
    """The deliberate exception to quarantine-and-ack.

    Every entry failing is not "a corrupt message", it is systemic — a
    gateway/worker version skew mid-rollout, say. Acking the lot would
    push real telemetry through a 10k-entry ring buffer and out the far
    side within twenty minutes at the default ingest rate, irrecoverably.
    Raising keeps the old wedge behaviour, which for *this* case is the
    right answer: nothing is acked, the entries stay in the stream, and
    fixing the cause drains them.
    """
    client = FakeRedis([("1-0", {"data": "{"}), ("2-0", {"data": "}"})])
    write = RecordingWriter()

    with pytest.raises(RuntimeError, match="failed to parse"):
        await _drain(client, write)

    assert write.written == []
    assert client.acked == [], "nothing may be acked when the whole batch failed"


async def test_a_single_unparseable_entry_alone_in_a_batch_is_still_quarantined() -> None:
    """The circuit-breaker must not swallow the case it was built around.

    A batch of exactly one bad entry is indistinguishable from "the only
    message that arrived this tick is corrupt" — quarantining it is what
    keeps the drain moving, and it is the original defect.
    """
    client = FakeRedis([("1-0", {"data": "{not json"})])
    write = RecordingWriter()

    result = await _drain(client, write)

    assert result.written == 0
    assert result.quarantined == 1
    assert client.acked == ["1-0"]


async def test_a_clean_batch_quarantines_nothing() -> None:
    client = FakeRedis([_valid_entry("1-0", "order-service"), _valid_entry("2-0", "payments")])
    write = RecordingWriter()

    result = await _drain(client, write)

    assert result == (2, 0)
    assert client.dead_lettered == []
    assert client.acked == ["1-0", "2-0"]


# ---- an entry Postgres refuses (F44-039, Phase 44 batch 3) ----------------------------
#
# An entry that parses but that Postgres will not store (a NUL byte in a
# text column, say) made the whole batch's write raise: nothing was acked,
# and the same batch was reclaimed and refused on every tick, every entry
# behind it stuck. It is quarantined with Postgres's reason now, as an
# unparseable entry is, and the drain carries on. A database that cannot
# be reached still acks nothing.


class RefusingWriter(RecordingWriter):
    """Postgres, refusing any row whose service name holds a NUL byte."""

    async def __call__(self, engine, rows: list[dict]) -> None:
        from sqlalchemy.exc import DataError

        if any("\x00" in row["service_name"] for row in rows):
            raise DataError("INSERT INTO raw_events ...", {}, ValueError("invalid byte sequence"))
        self.written.extend(rows)


async def test_an_entry_postgres_refuses_is_quarantined_and_the_rest_written() -> None:
    client = FakeRedis(
        [
            _valid_entry("1-0", "order-service"),
            _valid_entry("2-0", "pay\x00ments"),
            _valid_entry("3-0", "inventory"),
        ]
    )
    write = RefusingWriter()

    result = await _drain(client, write)

    assert [row["service_name"] for row in write.written] == ["order-service", "inventory"]
    assert result == (2, 1)
    assert client.acked == ["1-0", "2-0", "3-0"]
    [quarantined] = client.dead_lettered
    assert quarantined["source_entry_id"] == "2-0"
    assert "Postgres refused" in quarantined["error"] and "DataError" in quarantined["error"]


async def test_a_batch_postgres_refuses_whole_raises_instead_of_acking() -> None:
    """As for parsing: every entry refused is systemic, not a bad entry."""
    client = FakeRedis([_valid_entry("1-0", "a\x00"), _valid_entry("2-0", "b\x00")])

    with pytest.raises(RuntimeError, match="refused"):
        await _drain(client, RefusingWriter())

    assert client.acked == []
    assert client.dead_lettered == []


async def test_a_database_that_cannot_be_reached_acks_nothing() -> None:
    from sqlalchemy.exc import OperationalError

    class Unreachable(RecordingWriter):
        async def __call__(self, engine, rows: list[dict]) -> None:
            raise OperationalError("connect", {}, ConnectionRefusedError("refused"))

    client = FakeRedis([_valid_entry("1-0", "order-service"), _valid_entry("2-0", "payments")])

    with pytest.raises(OperationalError):
        await _drain(client, Unreachable())

    assert client.acked == []
    assert client.dead_lettered == []
