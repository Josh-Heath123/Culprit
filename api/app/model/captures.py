"""Storing and reading CONFIGURED captures (Phase 30, fields 5 and 9).

`POST /captures` takes the sealed envelope `culprit env capture` writes,
verifies it (app/model/envelope.py), checks every fact's grant against
the capture's own grant list, and writes one `captures` row plus N
`configured_facts` rows in one transaction. `GET /captures/{id}` and
`GET /captures/diff` read them back.

# Every value names a grant the capture actually held

`configured_facts` refuses a value with no `grant_ref` (Phase 26.1), and
the CLI names one on every fact — the capability that permitted reading
it, per-key for a config value. This module is where that stops being a
free-text column: a fact whose `grant_ref` is not in the capture's own
`grants` is refused, and a config *value* must name exactly
`config.read.values:<component>/<KEY>` for its own subject, on that
capability's allowlist. docs/LIMITS.md recorded, until Phase 30, that
"nothing validates that the grant it names is real". This does, against
the only grant list there is — the one the capture ran under.

# One serialiser for a stored fact

`fact_out` is the only way a stored fact becomes part of a response, and
it renders through `culprit_model.capture_diff.render_value`, which never
prints a config value — granted or not. `api-reader` has SELECT on
`configured_facts.value` (migration e4c1b7a9d2f0 argues why), so this
function is the enforcement point for the dashboard, and
`api/tests/test_captures_api.py` plants a granted value and asserts no
endpoint returns it.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from culprit_model.capabilities import ALLOWLISTED, Capability
from culprit_model.capture_diff import DiffEntry, StoredFact, diff_captures, render_value
from culprit_model.facts import Fact
from culprit_model.protocol import CaptureBundle
from culprit_model.shape import ValueShape
from culprit_model.subjects import SubjectError, SubjectKind, parse
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Capture, ConfiguredFact
from app.facts.service import DuplicateCapture, MismatchedCaptureId, RejectedByDatabase
from app.model.envelope import Opened

#: Postgres SQLSTATE for a unique/primary-key violation.
_UNIQUE_VIOLATION = "23505"



class UngrantedFact(ValueError):
    """A fact whose grant the capture did not hold.

    Named by index, never by subject or value, for the reason every
    rejection on this path is (docs/LIMITS.md, "A malformed capture tells
    you which fact, not which subject").
    """

    def __init__(self, index: int, rule: str) -> None:
        super().__init__(f"facts.{index}: {rule}")


def _is_config(subject: str) -> tuple[bool, dict[str, str]]:
    try:
        kind, parts = parse(subject)
    except SubjectError:
        return True, {}
    return kind is SubjectKind.CONFIG, parts


def check_grants(bundle: CaptureBundle) -> None:
    """Every value-bearing fact must name a grant this capture held."""
    held: dict[str, set[str]] = {grant.capability: set(grant.allow) for grant in bundle.grants}
    for index, fact in enumerate(bundle.facts):
        if fact.value is None and fact.grant_ref is None:
            continue
        if fact.grant_ref is None:
            raise UngrantedFact(index, "carries a value but names no grant")
        capability, _, item = fact.grant_ref.partition(":")
        if capability not in Capability.__members__.values():
            raise UngrantedFact(index, "names a capability that does not exist")
        if capability not in held:
            raise UngrantedFact(index, "names a grant this capture does not list")
        if Capability(capability) in ALLOWLISTED and item not in held[capability]:
            raise UngrantedFact(index, "names an item that is not on its grant's allowlist")
        is_config, parts = _is_config(fact.subject)
        if is_config and fact.value is not None and not isinstance(fact.value, bool):
            expected = f"config.read.values:{parts.get('component', '')}/{parts.get('key', '')}"
            if fact.grant_ref != expected:
                raise UngrantedFact(
                    index, "carries a config value under a grant that is not its own key's"
                )


def _configured_row(fact: Fact, bundle: CaptureBundle) -> dict[str, Any]:
    """One `configured_facts` row for a Core insert (no RETURNING — see
    `app/facts/service.py`'s `_intent_row` for why that is a privilege
    decision, not a style one)."""
    return dict(
        id=uuid4(),
        capture_id=bundle.capture_id,
        environment=bundle.environment,
        subject=fact.subject,
        predicate=fact.predicate,
        value=fact.canonical if fact.value is not None else None,
        value_shape=(
            fact.value_shape.model_dump(mode="json", exclude_none=True)
            if fact.value_shape is not None
            else None
        ),
        grant_ref=fact.grant_ref,
        source_kind=str(fact.provenance.source_kind),
        extractor=fact.provenance.extractor,
        artefact=fact.provenance.artefact,
        locator=fact.provenance.locator,
        captured_at=fact.captured_at,
    )


def _sqlstate(exc: IntegrityError) -> str:
    orig = getattr(exc, "orig", None)
    driver = getattr(orig, "__cause__", None) or orig
    return str(getattr(driver, "sqlstate", "") or "")


async def store_capture(session: AsyncSession, opened: Opened) -> Capture:
    bundle = opened.bundle
    mismatched = next(
        (index for index, fact in enumerate(bundle.facts) if fact.capture_id != bundle.capture_id),
        None,
    )
    if mismatched is not None:
        raise MismatchedCaptureId(mismatched)
    check_grants(bundle)

    existing = (
        await session.execute(select(Capture.id).where(Capture.id == bundle.capture_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateCapture(bundle.capture_id)

    session.add(
        Capture(
            id=bundle.capture_id,
            plane=str(bundle.plane),
            environment=bundle.environment,
            extractor=bundle.extractor,
            started_at=bundle.started_at,
            finished_at=bundle.finished_at or datetime.now(UTC),
            digest=opened.digest,
            signed_by=opened.signed_by,
            grants=[grant.model_dump(mode="json") for grant in bundle.grants],
            refused=[refusal.model_dump(mode="json") for refusal in bundle.refused],
        )
    )
    try:
        if bundle.facts:
            await session.execute(
                insert(ConfiguredFact), [_configured_row(fact, bundle) for fact in bundle.facts]
            )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _sqlstate(exc) == _UNIQUE_VIOLATION:
            raise DuplicateCapture(bundle.capture_id) from exc
        raise RejectedByDatabase(exc) from exc

    return (
        await session.execute(select(Capture).where(Capture.id == bundle.capture_id))
    ).scalar_one()


# --- reading back -----------------------------------------------------


def _stored(row: ConfiguredFact) -> StoredFact:
    return StoredFact(
        subject=row.subject,
        predicate=row.predicate,
        value=row.value,
        value_shape=ValueShape.model_validate(row.value_shape) if row.value_shape else None,
    )


def fact_out(row: ConfiguredFact) -> dict[str, Any]:
    """The only serialiser for a stored CONFIGURED fact. See the module
    docstring: `value` here is always the rendered form, never the column."""
    return {
        "subject": row.subject,
        "predicate": row.predicate,
        "value": render_value(_stored(row)),
        "grant_ref": row.grant_ref,
        "extractor": row.extractor,
        "artefact": row.artefact,
    }


async def get_capture(
    session: AsyncSession, capture_id: UUID
) -> tuple[Capture, list[ConfiguredFact]] | None:
    capture = (
        await session.execute(select(Capture).where(Capture.id == capture_id))
    ).scalar_one_or_none()
    if capture is None or capture.plane != "CONFIGURED":
        return None
    facts = (
        await session.execute(
            select(ConfiguredFact)
            .where(ConfiguredFact.capture_id == capture_id)
            .order_by(ConfiguredFact.subject, ConfiguredFact.predicate)
        )
    ).scalars().all()
    return capture, list(facts)


def diff(a: list[ConfiguredFact], b: list[ConfiguredFact]) -> list[DiffEntry]:
    return diff_captures([_stored(row) for row in a], [_stored(row) for row in b])
