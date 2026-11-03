"""Persisting readings (Phase 31).

# Append, not upsert

`divergences` is a record of open problems, so a repeat sighting is an
UPDATE there. `readings` is the opposite kind of table: it is evidence
accumulating over time, a TimescaleDB hypertable partitioned on
`taken_at` and retained ninety days. "The database was unreachable at
14:02 and reachable at 14:07" is two readings, and collapsing them would
destroy the only thing a reading is for.

So every reading is an INSERT. The one thing collapsed is an exact
duplicate *within a single batch* — same probe, same target, same
environment, same instant — which is not history repeating but the same
measurement submitted twice, and which a retrying agent produces without
meaning to.

# Why a Core insert

`insert()` over a mapping list, not ORM objects, and that is a privilege
decision rather than a style one — exactly as `app/facts/service.py`
explains. The ORM would write with `INSERT ... RETURNING` to fetch the
server-side defaults back, and Postgres requires SELECT on a table to
return anything from it. That would force a SELECT grant on `readings`,
letting a leaked probe credential read the whole evidence log instead of
only appending to it. A Core insert emits no RETURNING, so `probe-writer`
stays at INSERT alone, and `id` is generated here rather than by the
column's `gen_random_uuid()` default so that nothing needs reading back.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from culprit_model.readings import Reading, redact_reading
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reading as ReadingRow


class RejectedByDatabase(Exception):
    """A row the database refused, reported without echoing the row.

    Same reasoning as `app/facts/service.py`'s and
    `app/divergences/service.py`'s: Postgres renders the failing row into
    its own error text, and a reading carries `evidence` and `measured`.
    The message here is built from the constraint name alone.
    """

    def __init__(self, exc: IntegrityError) -> None:
        orig = getattr(exc, "orig", None)
        driver = getattr(orig, "__cause__", None) or orig
        self.constraint = str(getattr(driver, "constraint_name", "") or "")
        reason = _CONSTRAINT_REASONS.get(self.constraint)
        if reason:
            super().__init__(f"a reading was refused by the database: {reason}")
        else:
            super().__init__(
                "a reading was refused by the database"
                + (f" (constraint {self.constraint})" if self.constraint else "")
            )


#: Constraint names this endpoint can trip, and what to tell the caller.
#: The message names the *rule*, never the row. Both are also enforced by
#: `culprit_model.readings.Reading` before a request reaches here, so
#: tripping one of these means a row arrived by some path the model did
#: not guard — worth a specific message precisely because it should not
#: happen.
_CONSTRAINT_REASONS = {
    "ck_readings_verdict": "verdict must be one of pass, fail, inconclusive, refused",
    "ck_readings_reason_required_when_unresolved": (
        "an inconclusive or refused reading must carry a reason"
    ),
}


class Stored:
    """How one batch landed, in the terms the caller asked about."""

    def __init__(self) -> None:
        self.stored = 0
        self.duplicates = 0


def _identity(reading: Reading) -> tuple[str, str, str, datetime]:
    """What makes two readings in one batch the same measurement.

    Deliberately not a database constraint. Two readings with this
    identity taken in two different batches are a probe that ran twice at
    a timestamp resolution coarser than the gap between the runs, which is
    a real thing that happens and is not an error.
    """
    return (reading.probe_id, reading.target, reading.environment, reading.taken_at)


def _row(reading: Reading) -> dict[str, Any]:
    """One `readings` row, as a plain mapping for a Core insert."""
    return dict(
        id=uuid4(),
        taken_at=reading.taken_at,
        probe_id=reading.probe_id,
        probe_version=reading.probe_version,
        target=reading.target,
        environment=reading.environment,
        verdict=str(reading.verdict),
        # `measured` and `expected` are already JSON-native — they reached
        # the model by being parsed out of a JSON body. The two nested
        # models are not, and go through `mode="json"`, so a `datetime` in
        # a `Provenance` becomes a string rather than reaching asyncpg as
        # a Python object it cannot put in a JSONB column.
        measured=reading.measured,
        expected=reading.expected,
        expected_source=(
            reading.expected_source.model_dump(mode="json") if reading.expected_source else None
        ),
        evidence=[item.model_dump(mode="json") for item in reading.evidence],
        reason=reading.reason or None,
        expires_at=reading.expires_at,
        agent_id=reading.agent_id,
        grants_used=[str(grant) for grant in reading.grants_used],
    )


async def store_readings(session: AsyncSession, readings: list[Reading]) -> Stored:
    """Insert every reading in one transaction. Returns what landed.

    No `now` parameter, unlike `store_divergences`: a reading's time is
    `taken_at`, which the probe that measured it set. When the server
    happened to receive it is not a fact about the measurement.
    """
    stored = Stored()

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, datetime]] = set()
    for reading in readings:
        identity = _identity(reading)
        if identity in seen:
            stored.duplicates += 1
            continue
        seen.add(identity)
        # Redact on the way in. The CLI already redacts before a Reading
        # exists, but this endpoint accepts readings from outside that
        # guarantee -- a third-party probe, an older binary, a
        # hand-written payload -- and what it accepts lands in a 90-day
        # hypertable `api-reader` can read. A store is a bad place to
        # discover that someone else's redaction had one more site.
        rows.append(_row(redact_reading(reading)))

    if not rows:
        return stored

    try:
        await session.execute(insert(ReadingRow), rows)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RejectedByDatabase(exc) from exc

    stored.stored = len(rows)
    return stored
