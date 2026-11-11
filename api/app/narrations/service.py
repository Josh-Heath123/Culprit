"""Reading a narration, and checking it again before serving it.

The worker runs `culprit_model.narration.check` before it writes a
narration; this runs it again on every read, as Phase 34 re-judges a
verification. A row that reached the table by any other route — inserted
by hand, by the table's owner — is not served as prose unless it passes.
Prose is never sent as prose: it is split into segments, and each citation
is replaced by its evidence item's text from the record.
"""

from typing import Any

from culprit_model.investigations import Investigation
from culprit_model.narration import MAX_PROSE, check, segments
from culprit_model.redaction import redact_credentials
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.narrations import tables
from app.narrations.config import NARRATION_PROVIDER
from app.narrations.schemas import NarrationSegment, NarrationView

#: The migration's CHECK: attempts 1 to 3.
MAX_ATTEMPTS = 3


async def view(session: AsyncSession, investigation: Investigation) -> NarrationView:
    narrations = tables.narrations
    attempts = (
        await session.execute(
            select(func.count())
            .select_from(narrations)
            .where(narrations.c.investigation_id == investigation.id)
        )
    ).scalar_one()
    newest = (
        (
            await session.execute(
                select(narrations)
                .where(narrations.c.investigation_id == investigation.id)
                .order_by(narrations.c.attempt.desc())
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    if newest is None:
        state = "off" if NARRATION_PROVIDER == "none" else "not_narrated"
        return NarrationView(state=state, attempts=0, max_attempts=MAX_ATTEMPTS)
    return served(investigation, dict(newest), attempts)


def served(investigation: Investigation, row: dict[str, Any], attempts: int) -> NarrationView:
    """The newest attempt as it may be shown. Pure, so the re-check is
    testable without a database."""
    base = {
        "attempts": attempts,
        "max_attempts": MAX_ATTEMPTS,
        "provider": row["provider"],
        "model": row["model"],
        "narrated_at": row["narrated_at"],
    }
    if row["status"] == "complete":
        prose = row["prose"] or ""
        if len(prose) > MAX_PROSE:
            return NarrationView(state="refused", named=["prose longer than allowed"], **base)
        result = check(investigation, prose)
        if not result.passed:
            return NarrationView(
                state="refused", named=[redact_credentials(n) for n in result.named], **base
            )
        return NarrationView(
            state="complete",
            segments=[
                NarrationSegment(text=segment.text, evidence=segment.evidence)
                for segment in segments(investigation, prose)
            ],
            **base,
        )
    if row["status"] == "failed":
        return NarrationView(
            state="failed", reason=redact_credentials(row["reason"] or "no reason"), **base
        )
    return NarrationView(
        state="refused",
        named=[redact_credentials(n) for n in (row["named"] or ["something it was not given"])],
        **base,
    )
