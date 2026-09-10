"""Persisting one run's findings (Phase 29 field 9).

# Upsert, not append

The table is a record of open problems, not a log of runs. A CI job that
runs on every push finds the same unfixed fault every time, and appending
would turn one problem into three hundred rows within a fortnight —
after which nobody could answer the only questions worth asking: what is
open, what is new, and how long has this been broken.

So each finding carries an identity (`Divergence.identity()`: subject,
predicate, and the two disagreeing sources) and a repeat sighting is an
UPDATE. `first_seen_at` keeps its meaning, `last_seen_at` moves, and the
response says how many were new.

# What is deliberately not done here

**Nothing is closed.** A finding that stops appearing is not marked
resolved by this endpoint, and that is not an omission. This run may have
checked a subset of components, or extraction may have been skipped for
a whole component (Phase 28's honesty rule means that shows as a skip,
not as an absence of findings). Inferring "it is fixed" from "I did not
see it" is the exact mistake the comparator refuses to make about facts,
and it would be no more defensible here. Resolution is a Phase 32
question, once verification exists to establish it.
"""

from datetime import UTC, datetime
from uuid import UUID

from culprit_model.facts import Divergence, DivergenceStatus
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Capture, DivergenceRow


class UnknownCapture(Exception):
    """A capture id that names nothing stored.

    Refused rather than stored with a dangling reference. The whole value
    of the link is that a reader can go from a finding back to the fact
    set it came from; a link to a capture that does not exist is worse
    than no link, because it looks like one.
    """

    def __init__(self, capture_id: UUID) -> None:
        self.capture_id = capture_id
        super().__init__(f"no capture {capture_id} has been stored")


class RejectedByDatabase(Exception):
    """A row the database refused, reported without echoing the row.

    The same reasoning as `app/facts/service.py`'s: Postgres renders the
    failing row into its own error text, and a divergence embeds two
    whole facts. The message here is built from the constraint name
    alone.
    """

    def __init__(self, exc: IntegrityError) -> None:
        orig = getattr(exc, "orig", None)
        driver = getattr(orig, "__cause__", None) or orig
        self.constraint = str(getattr(driver, "constraint_name", "") or "")
        super().__init__(
            "a divergence was refused by the database"
            + (f" (constraint {self.constraint})" if self.constraint else "")
        )


class Stored:
    """How one upload landed, in the terms the caller asked about."""

    def __init__(self) -> None:
        self.first_seen = 0
        self.seen_again = 0
        self.suppressed = 0


async def store_divergences(
    session: AsyncSession,
    divergences: list[Divergence],
    capture_id: UUID | None,
    *,
    now: datetime | None = None,
) -> Stored:
    """Upsert every finding, in one transaction."""
    moment = now or datetime.now(UTC)
    stored = Stored()

    if capture_id is not None:
        exists = await session.scalar(select(Capture.id).where(Capture.id == capture_id))
        if exists is None:
            raise UnknownCapture(capture_id)

    try:
        for divergence in divergences:
            if divergence.status is DivergenceStatus.SUPPRESSED:
                stored.suppressed += 1
            if await _upsert(session, divergence, capture_id, moment):
                stored.first_seen += 1
            else:
                stored.seen_again += 1
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RejectedByDatabase(exc) from exc

    return stored


async def _upsert(
    session: AsyncSession,
    divergence: Divergence,
    capture_id: UUID | None,
    moment: datetime,
) -> bool:
    """Insert or refresh one finding. True when it had not been seen."""
    key = divergence.identity()

    values = {
        "divergence_key": key,
        "kind": str(divergence.kind),
        "subject": divergence.subject,
        "predicate": divergence.predicate,
        # `model_dump(mode="json")` rather than the raw dict: the column is
        # JSONB and a `datetime` is not JSON. Round-tripping through the
        # model's own serialiser also means the stored fact is exactly
        # what a reader will get back, rather than a near-miss.
        "left_fact": divergence.left.model_dump(mode="json"),
        "right_fact": divergence.right.model_dump(mode="json"),
        "environment": divergence.left.environment,
        "severity": str(divergence.severity),
        "status": str(divergence.status),
        "explanation": divergence.explanation or None,
        "severity_reason": divergence.severity_reason or None,
        "suppressed_by": divergence.suppressed_by or None,
        "capture_id": capture_id,
        "first_seen_at": divergence.first_seen_at or moment,
        "last_seen_at": moment,
    }

    statement = (
        insert(DivergenceRow)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["divergence_key"],
            set_={
                # Everything about the finding *except* `first_seen_at`,
                # which is the one column a repeat sighting must not
                # touch. Severity and explanation are refreshed because
                # the system model may have changed since the first
                # sighting and the current answer is the useful one; the
                # stored history of what it *was* is a Phase 32 question,
                # and pretending to answer it with a single row would be
                # worse than not answering it.
                "severity": statement_value(values, "severity"),
                "status": statement_value(values, "status"),
                "explanation": statement_value(values, "explanation"),
                "severity_reason": statement_value(values, "severity_reason"),
                "suppressed_by": statement_value(values, "suppressed_by"),
                "left_fact": statement_value(values, "left_fact"),
                "right_fact": statement_value(values, "right_fact"),
                "capture_id": statement_value(values, "capture_id"),
                "last_seen_at": moment,
            },
        )
        # `xmax = 0` is true only for a row this statement inserted, and
        # non-zero for one it updated. It is the standard way to tell the
        # two apart in a single round trip, and the alternative — SELECT
        # then INSERT — is a race between two concurrent CI jobs, which
        # is precisely the situation a busy repository is in.
        .returning(literal_column("(xmax = 0)").label("was_inserted"))
    )

    result = await session.execute(statement)
    row = result.first()
    if row is None:  # pragma: no cover - on_conflict_do_update always returns
        return False
    return bool(row.was_inserted)


def statement_value(values: dict, name: str) -> object:
    """The value being written, for the ON CONFLICT branch.

    A named helper rather than `values[name]` inline so the intent is
    legible: the update writes the *new* values, not the excluded-row
    magic that is easy to reach for and easy to get subtly wrong.
    """
    return values[name]
