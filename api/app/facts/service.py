"""Persisting a capture bundle (Phase 28 field 8/9).

One bundle becomes one `captures` row and N `intent_facts` rows, in one
transaction. Partial is not an option: a capture is a snapshot, and half
a snapshot compares against a whole one and manufactures divergences that
describe nothing but the failed upload.

**Only INTENT is accepted this phase.** `CONFIGURED` and `OBSERVED`
captures are Phases 30 and 31, and `fact-writer` has no grant on
`configured_facts` or `readings` — so a bundle on either plane is
refused here, with a message saying which phase it belongs to, rather
than being allowed through to fail as a Postgres permission error the
caller cannot act on.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from culprit_model.facts import Fact
from culprit_model.planes import Plane
from culprit_model.protocol import CaptureBundle
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Capture, IntentFact


class UnsupportedPlane(Exception):
    """A bundle on a plane this phase cannot store."""

    def __init__(self, plane: Plane) -> None:
        self.plane = plane
        super().__init__(
            f"{plane} captures are not accepted yet — this build stores INTENT only "
            "(CONFIGURED lands in Phase 30, OBSERVED in Phase 31)"
        )


class DuplicateCapture(Exception):
    """A capture id that has already been stored.

    The client chooses `capture_id` (it is derived from the capture's own
    content and time, so it is stable and reproducible — see
    `DeriveCaptureID` in the CLI). A retry of a request that already
    succeeded therefore arrives with the same id, which is a normal
    event, not a server fault. Reported as a 409 rather than letting the
    primary-key violation surface as a 500 with a traceback in the log.
    """

    def __init__(self, capture_id: object) -> None:
        self.capture_id = capture_id
        super().__init__(f"capture {capture_id} has already been stored")


#: Postgres SQLSTATE for a unique/primary-key violation.
_UNIQUE_VIOLATION = "23505"

#: Constraint names this endpoint can plausibly trip, and what to tell
#: the caller. The message names the *rule*, never the row: Postgres's
#: own error text carries `DETAIL: Failing row contains (...)`, which for
#: a config fact is the value the constraint was refusing.
_CONSTRAINT_REASONS = {
    "ck_intent_facts_value_requires_grant": (
        "a fact about a config key may not carry a literal value without a grant_ref"
    ),
    "ck_intent_facts_value_shape_is_closed": (
        "value_shape must be exactly {type, length_class, format, present} with "
        "values from the closed vocabulary"
    ),
    "ck_intent_facts_grant_ref_not_blank": "grant_ref may not be blank",
    "ck_captures_environment_matches_plane": (
        "an INTENT capture may not carry an environment"
    ),
}


def _driver_error(exc: IntegrityError) -> object:
    """The asyncpg exception underneath SQLAlchemy's two wrappers.

    `exc.orig` is SQLAlchemy's `AsyncAdapt_asyncpg_dbapi.IntegrityError`,
    which carries `sqlstate` but **not** `constraint_name`; the real
    `asyncpg.exceptions.CheckViolationError` is its `__cause__` and has
    both. Reading only `exc.orig` therefore found no constraint name and
    fell back to a generic message — a small thing, except the specific
    message is the entire reason this path exists rather than a 500.
    Verified against a live database rather than assumed.
    """
    orig = getattr(exc, "orig", None)
    return getattr(orig, "__cause__", None) or orig


def _sqlstate(exc: IntegrityError) -> str:
    """The SQLSTATE of the underlying driver error, or "" if unavailable."""
    return str(getattr(_driver_error(exc), "sqlstate", "") or "")


class RejectedByDatabase(Exception):
    """A row the database refused, reported without echoing the row.

    The exception text Postgres produces for a CHECK violation includes
    the failing row — which for a config fact is the credential the
    constraint was refusing to store. So the message here is built from
    the *constraint name* alone, and the original is chained but never
    rendered into a response.
    """

    def __init__(self, exc: IntegrityError) -> None:
        name = str(getattr(_driver_error(exc), "constraint_name", "") or "")
        reason = _CONSTRAINT_REASONS.get(name)
        self.constraint = name
        if reason:
            super().__init__(f"a fact was refused by the database: {reason}")
        else:
            super().__init__(
                "a fact was refused by the database"
                + (f" (constraint {name})" if name else "")
            )


class MismatchedCaptureId(Exception):
    """A fact claiming to belong to a different capture than the bundle.

    Refused rather than silently rewritten. `capture_id` is what makes a
    snapshot queryable as a snapshot; a fact carrying someone else's is
    either a client bug or two bundles spliced together, and quietly
    fixing it up would hide both.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        # The *index*, not the subject. The subject is attacker-controlled
        # text that this message would otherwise echo into a 422 body and
        # the access log — and a subject is exactly where somebody would
        # hide a value. `facts.3` is just as actionable.
        super().__init__(f"facts.{index} carries a different capture_id than its bundle")


def _intent_row(fact: Fact, bundle: CaptureBundle) -> dict[str, Any]:
    """One `intent_facts` row, as a plain mapping for a Core insert.

    A mapping and a Core `insert()`, not ORM objects, and that is a
    privilege decision rather than a style one. The ORM writes a row with
    server-side defaults using `INSERT ... RETURNING`, and Postgres
    requires SELECT on a table to return anything from it — so the ORM
    path forces a SELECT grant on `intent_facts`, which would let a
    leaked CI token read every capture ever stored rather than only
    append to them. A Core insert emits no RETURNING, so `fact-writer`
    stays at INSERT alone. (Found by the test asserting exactly that
    grant set: the insert failed with "permission denied for table
    intent_facts" while holding INSERT on it.)
    """
    return dict(
        id=uuid4(),
        capture_id=bundle.capture_id,
        subject=fact.subject,
        predicate=fact.predicate,
        # `canonical`, not the raw value: comparison in Phase 29 reads
        # these rows back and compares them, and canonicalising on the
        # way in means two extractors that ordered a mapping differently
        # do not read as a divergence later.
        value=fact.canonical,
        # Carried, not dropped. Half the config facts an INTENT capture
        # produces are shape-only (`predicate: value_shape`, no value at
        # all), and storing them with the shape discarded left the
        # response reporting facts it had effectively thrown away.
        value_shape=fact.value_shape.model_dump() if fact.value_shape else None,
        grant_ref=fact.grant_ref,
        source_kind=str(fact.provenance.source_kind),
        extractor=fact.provenance.extractor,
        artefact=fact.provenance.artefact,
        locator=fact.provenance.locator,
        confidence_rank=fact.provenance.confidence_rank,
        captured_at=fact.captured_at,
    )


async def store_capture(session: AsyncSession, bundle: CaptureBundle) -> Capture:
    """Writes a bundle. Returns the persisted `captures` row.

    The caller's session is committed here rather than by the router, so
    the whole bundle lands or none of it does.
    """
    if bundle.plane is not Plane.INTENT:
        raise UnsupportedPlane(bundle.plane)

    mismatched = next(
        (
            index
            for index, fact in enumerate(bundle.facts)
            if fact.capture_id != bundle.capture_id
        ),
        None,
    )
    if mismatched is not None:
        raise MismatchedCaptureId(mismatched)

    capture = Capture(
        id=bundle.capture_id,
        plane=str(bundle.plane),
        # NULL exactly when the plane is INTENT — a check constraint in
        # c07a5f31d8e4 enforces it, and INTENT is the only plane this
        # phase accepts, so it is always NULL here.
        environment=None,
        extractor=bundle.extractor,
        started_at=bundle.started_at,
        finished_at=bundle.finished_at or datetime.now(UTC),
    )
    existing = (
        await session.execute(select(Capture.id).where(Capture.id == bundle.capture_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateCapture(bundle.capture_id)

    session.add(capture)
    # The insert is inside the try, not before it, and that placement is
    # the whole fix. SQLAlchemy autoflushes the pending `Capture` when
    # this executes, so a duplicate capture id and every CHECK violation
    # are both raised *here* rather than at commit(). With the insert
    # outside, they escaped uncaught: a 500, and starlette wrote the
    # traceback — which for a CHECK violation includes Postgres's
    # `DETAIL: Failing row contains (...)`, values and all — into the API
    # log. That is exactly what api/app/errors.py exists to prevent, on a
    # path it does not cover. (Both found by the Phase 28 invariant
    # audit; the concurrent-duplicate 409 it also broke only ever worked
    # for an empty bundle, which is the case that never happens.)
    try:
        if bundle.facts:
            await session.execute(
                insert(IntentFact), [_intent_row(fact, bundle) for fact in bundle.facts]
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Discriminated on SQLSTATE, not caught wholesale. A blanket
        # "IntegrityError means duplicate" would report every constraint
        # failure as "already stored" — a confidently wrong answer, and
        # the wrong status code, for what is usually a malformed fact.
        if _sqlstate(exc) == _UNIQUE_VIOLATION:
            raise DuplicateCapture(bundle.capture_id) from exc
        raise RejectedByDatabase(exc) from exc

    # Re-read rather than refresh: `session.refresh` on the ORM object
    # would re-issue the same insert path's identity map lookup, and this
    # only needs the two server-defaulted columns back. SELECT on
    # `captures` is granted; SELECT on `intent_facts` deliberately is not.
    stored = (
        await session.execute(select(Capture).where(Capture.id == bundle.capture_id))
    ).scalar_one()
    return stored
