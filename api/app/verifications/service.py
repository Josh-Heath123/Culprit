"""Storing verifications, and the outcomes they make (Phase 34 part 2).

**What the API checks that the type cannot.** `Verification` holds its own
record together — the verdict is `judge()`'s, or the body does not parse —
but it cannot see the investigation it points at. Here, against the stored
investigation, read under `api-reader`:

- it re-ran the investigation's **full** reading set: every reading, and no
  other;
- each re-run's `was`, probe, target and environment are the stored
  reading's;
- every run was taken after the investigation closed — a run from before
  it is a stored reading reused, not a measurement of the fix.

Each refusal names what failed and nothing of the content.

**Redaction at the same choke point as a reading** (standing invariant 11):
every run passes through `redact_reading`, and the free text a
verification adds — its reason, an action's words — through
`redact_credentials`, before `verification-writer` inserts it. The
investigation is never written to.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from culprit_model.investigations import Investigation
from culprit_model.readings import redact_reading
from culprit_model.redaction import redact_credentials
from culprit_model.subjects import SubjectError
from culprit_model.subjects import parse as parse_subject
from culprit_model.verifications import Verification, VerificationVerdict
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.verifications import tables

#: How far past this server's clock a run may be stamped: the agents'
#: signing skew (app/agents/signing.py, 300 s). A run from the future is a
#: clock that is wrong, or a record that was not measured.
FUTURE_SKEW = timedelta(seconds=300)


class Refused(Exception):
    """A verification the investigation it names does not support. The
    message is safe to return."""


class AlreadyStored(Exception):
    pass


def check_against(investigation: Investigation, verification: Verification) -> None:
    """Refuse a verification its investigation does not support."""
    if verification.investigation_id != investigation.id:
        raise Refused(
            f"the verification is of {verification.investigation_id}, not {investigation.id}"
        )
    if verification.environment != investigation.environment:
        raise Refused(
            f"the verification ran in {verification.environment}; "
            f"the investigation is of {investigation.environment}"
        )
    stored = {item.id: item.reading for item in investigation.readings}
    reran = {rerun.reading_id: rerun for rerun in verification.reran}
    missing = sorted(set(stored) - set(reran))
    extra = sorted(set(reran) - set(stored))
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"does not re-run {', '.join(missing)}")
        if extra:
            parts.append(f"re-runs {', '.join(extra)}, which the investigation does not hold")
        raise Refused(
            "a verification re-runs the investigation's full reading set; this one "
            + " and ".join(parts)
        )
    closed = investigation.closed_at or investigation.opened_at
    latest = datetime.now(UTC) + FUTURE_SKEW
    for reading_id, rerun in reran.items():
        reading = stored[reading_id]
        if rerun.was is not reading.verdict:
            raise Refused(
                f"re-run of {reading_id} says it was {rerun.was.value}; "
                f"the investigation recorded {reading.verdict.value}"
            )
        if (rerun.probe_id, rerun.target, rerun.environment) != (
            reading.probe_id,
            reading.target,
            reading.environment,
        ):
            raise Refused(
                f"re-run of {reading_id} measured {rerun.probe_id} on {rerun.target} in "
                f"{rerun.environment}; the reading is {reading.probe_id} on {reading.target} "
                f"in {reading.environment}"
            )
        for run in rerun.runs:
            if run.taken_at <= closed:
                raise Refused(
                    f"a run of {reading_id} was taken at {run.taken_at.isoformat()}, before the "
                    f"investigation closed at {closed.isoformat()}: a verification measures "
                    "again, and never reuses a reading"
                )
            if run.taken_at > latest:
                raise Refused(
                    f"a run of {reading_id} was taken at {run.taken_at.isoformat()}, after now: "
                    "a verification records what was measured, never what will be"
                )
    # verified_at orders an investigation's verifications and picks the
    # one its outcome is: it may not precede what it judged, nor lie in
    # the future, or one post could stay "newest" for ever.
    measured = max(run.taken_at for rerun in reran.values() for run in rerun.runs)
    if verification.verified_at < measured:
        raise Refused(
            f"the verification says it was judged at {verification.verified_at.isoformat()}, "
            f"before its last run at {measured.isoformat()}"
        )
    if verification.verified_at > latest:
        raise Refused(
            f"the verification says it was judged at {verification.verified_at.isoformat()}, "
            "after now"
        )


async def source_of(session: AsyncSession, investigation_id: str) -> str | None:
    """The source earlier verifications of this investigation recorded, if
    any: one investigation's fault was planted or it was not."""
    return (
        await session.execute(
            select(tables.verifications.c.source)
            .where(tables.verifications.c.investigation_id == investigation_id)
            .limit(1)
        )
    ).scalar_one_or_none()


def sanitised(verification: Verification) -> Verification:
    """The verification as it will be stored: every run redacted, every
    piece of free text too. Rebuilt through the model, so the stored form
    is judged again."""
    payload = verification.model_dump(mode="json")
    payload["reran"] = [
        {
            **rerun.model_dump(mode="json"),
            "runs": [redact_reading(run).model_dump(mode="json") for run in rerun.runs],
        }
        for rerun in verification.reran
    ]
    payload["reason"] = redact_credentials(verification.reason)
    payload["applied_change"] = [
        {**change, "description": redact_credentials(change["description"])}
        if change.get("description")
        else change
        for change in payload["applied_change"]
    ]
    return Verification.model_validate(payload)


async def store(
    session: AsyncSession, verification: Verification, source: str, submitted_by: str
) -> None:
    try:
        await session.execute(
            insert(tables.verifications).values(
                id=verification.id,
                investigation_id=verification.investigation_id,
                environment=verification.environment,
                verdict=verification.verdict.value,
                failing_now_passes=verification.failing_now_passes,
                no_regressions=verification.no_regressions,
                changes_explained=verification.changes_explained,
                verified_at=verification.verified_at,
                source=source,
                submitted_by=submitted_by,
                verification=verification.model_dump(mode="json"),
                ingested_at=datetime.now(UTC),
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        orig = getattr(exc, "orig", None)
        driver = getattr(orig, "__cause__", None) or orig
        if str(getattr(driver, "constraint_name", "")) == "verifications_pkey":
            raise AlreadyStored from exc
        raise


async def list_for(session: AsyncSession, investigation_id: str) -> list[dict[str, Any]]:
    """Newest first: by when it was verified, then when it was stored."""
    rows = (
        await session.execute(
            select(tables.verifications)
            .where(tables.verifications.c.investigation_id == investigation_id)
            .order_by(
                tables.verifications.c.verified_at.desc(),
                tables.verifications.c.ingested_at.desc(),
                tables.verifications.c.id.desc(),
            )
        )
    ).mappings()
    return [
        {
            "verification": Verification.model_validate(row["verification"]),
            "source": row["source"],
            "submitted_by": row["submitted_by"],
            "ingested_at": row["ingested_at"],
        }
        for row in rows
    ]


# ---- outcomes -----------------------------------------------------------------------

METHOD = (
    "An outcome is the latest verification of an investigation whose diagnosis is "
    "complete. Its fault class is the subject kind of the diagnosis's root, read from the "
    "stored investigation. Per class and source, every verdict is counted; verified_share "
    "is verified divided by the decided outcomes (every verdict but inconclusive), and "
    "inconclusive is reported beside it, never folded in. A source of 'planted' means the "
    "fault was planted on purpose — a drill or the fault library — and says nothing of "
    "accuracy on a real system; 'real' means whoever asked for the verification said the "
    "fault happened on one — declared, not observed, and the same for every verification "
    "of one investigation. What a 'verified' outcome shows is that the fix applied for the "
    "root the walk diagnosed was seen to fix what the walk saw failing; a fault diagnosed "
    "at the wrong root is filed under that root's class, so this is not a measure of "
    "whether diagnoses named the true cause."
)

_NOTHING = (
    "No outcomes are recorded: no investigation with a complete diagnosis has been "
    "verified. There is no accuracy to report — not 0%, and not 100%."
)

_LATEST = text(
    """
    SELECT DISTINCT ON (v.investigation_id)
           v.investigation_id, v.verdict, v.source, i.complete, i.root_subject
    FROM verifications v
    JOIN investigations i ON i.id = v.investigation_id
    ORDER BY v.investigation_id, v.verified_at DESC, v.ingested_at DESC, v.id DESC
    """
)


def fault_class(root_subject: str | None) -> str:
    """The subject kind of a diagnosis's root."""
    try:
        kind, _ = parse_subject(root_subject or "")
    except SubjectError:
        return "unknown"
    return kind.value


def tally(latest: list[dict[str, Any]]) -> dict[str, Any]:
    """The accuracy report from each investigation's latest verification —
    pure, so the numbers are a function of the rows and nothing else."""
    partial = 0
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {verdict.value: 0 for verdict in VerificationVerdict}
    )
    for row in latest:
        if row["complete"] is not True:
            partial += 1
            continue
        groups[(fault_class(row["root_subject"]), row["source"])][row["verdict"]] += 1
    classes = []
    for (klass, source), verdicts in sorted(
        groups.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        outcomes = sum(verdicts.values())
        inconclusive = verdicts["inconclusive"]
        decided = outcomes - inconclusive
        classes.append(
            {
                "fault_class": klass,
                "source": source,
                "outcomes": outcomes,
                "verdicts": verdicts,
                "decided": decided,
                "verified_share": (verdicts["verified"] / decided) if decided else None,
                "inconclusive": inconclusive,
            }
        )
    outcomes = sum(item["outcomes"] for item in classes)
    return {
        "method": METHOD,
        "outcomes": outcomes,
        "partial_diagnoses_not_counted": partial,
        "classes": classes,
        "statement": None if outcomes else _NOTHING,
    }


async def accuracy(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(_LATEST)).mappings().all()
    return tally([dict(row) for row in rows])
