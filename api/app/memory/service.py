"""DB access for engineering-memory records (Phase 21,
docs/AI_NATIVE_PLAN.md) — the `postmortem-writer` role for writes
(reused, not a new role — invariant 10), whatever engine the caller
passes for reads. Transform logic (ORM row -> *Out) lives here too, not a
separate transforms.py — same reasoning as
app/postmortems/service.py's own module docstring: this package is small
enough that the split app/incidents/ uses would just be indirection.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AiChangeRecord, ArchitectureDecision
from app.memory.schemas import (
    AiChangeRecordCreate,
    AiChangeRecordOut,
    ArchitectureDecisionCreate,
    ArchitectureDecisionOut,
    ArchitectureDecisionPatch,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: Same truncation convention as app/postmortems/service.py's
#: LIST_BODY_TRUNCATE_CHARS.
LIST_BODY_TRUNCATE_CHARS = 280


def _embedding_status(
    embedded_at: datetime | None, embedding_error: str | None
) -> Literal["pending", "embedded", "failed"]:
    """Same ordering and reasoning as app/postmortems/service.py's own
    _embedding_status: a stale (pre-edit) embedding can coexist with a
    fresh embedding_error, and the failed state must win that check."""
    if embedding_error is not None:
        return "failed"
    if embedded_at is not None:
        return "embedded"
    return "pending"


# --- Architecture decisions -------------------------------------------


def _decision_out(
    decision: ArchitectureDecision, *, truncate_body: bool = False
) -> ArchitectureDecisionOut:
    body = decision.body
    if truncate_body and len(body) > LIST_BODY_TRUNCATE_CHARS:
        body = body[:LIST_BODY_TRUNCATE_CHARS].rstrip() + "…"
    return ArchitectureDecisionOut(
        id=decision.id,
        title=decision.title,
        body=body,
        author_user_id=decision.author_user_id,
        embedding_status=_embedding_status(decision.embedded_at, decision.embedding_error),
        embedding_error=decision.embedding_error,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


async def list_architecture_decisions(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[ArchitectureDecisionOut], int]:
    total = (
        await session.execute(select(func.count()).select_from(ArchitectureDecision))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(ArchitectureDecision)
                .order_by(ArchitectureDecision.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_decision_out(row, truncate_body=True) for row in rows], total


async def get_architecture_decision(
    session: AsyncSession, decision_id: UUID
) -> ArchitectureDecisionOut | None:
    decision = await session.get(ArchitectureDecision, decision_id)
    if decision is None:
        return None
    return _decision_out(decision)


async def create_architecture_decision(
    session: AsyncSession, data: ArchitectureDecisionCreate, *, author_user_id: UUID
) -> ArchitectureDecisionOut:
    decision = ArchitectureDecision(
        title=data.title, body=data.body, author_user_id=author_user_id
    )
    session.add(decision)
    await session.commit()
    await session.refresh(decision)
    return _decision_out(decision)


async def patch_architecture_decision(
    session: AsyncSession, decision_id: UUID, patch: ArchitectureDecisionPatch
) -> tuple[ArchitectureDecisionOut, bool] | None:
    """Returns (updated decision, should_reembed) -- same body-only
    re-embed trigger as app/postmortems/service.py::patch_postmortem: a
    decision's embedding is computed from `body` alone, so a title-only
    edit must not re-embed, and a retry on an already-failed decision
    (embedding_error is not None) always re-enqueues, including on an
    entirely empty patch."""
    decision = await session.get(ArchitectureDecision, decision_id)
    if decision is None:
        return None

    fields = patch.model_dump(exclude_unset=True)
    body_changed = "body" in fields and fields["body"] != decision.body
    should_reembed = body_changed or decision.embedding_error is not None

    if "title" in fields:
        decision.title = fields["title"]
    if "body" in fields:
        decision.body = fields["body"]
    if fields:
        decision.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(decision)
    return _decision_out(decision), should_reembed


async def delete_architecture_decision(session: AsyncSession, decision_id: UUID) -> bool:
    decision = await session.get(ArchitectureDecision, decision_id)
    if decision is None:
        return False
    await session.delete(decision)
    await session.commit()
    return True


# --- AI change records --------------------------------------------------


def _change_record_out(record: AiChangeRecord) -> AiChangeRecordOut:
    return AiChangeRecordOut(
        id=record.id,
        commit_sha=record.commit_sha,
        summary=record.summary,
        files_changed=list(record.files_changed),
        git_author=record.git_author,
        author_user_id=record.author_user_id,
        embedding_status=_embedding_status(record.embedded_at, record.embedding_error),
        embedding_error=record.embedding_error,
        committed_at=record.committed_at,
        created_at=record.created_at,
    )


async def list_ai_change_records(
    session: AsyncSession, limit: int, offset: int, since: datetime | None = None
) -> tuple[list[AiChangeRecordOut], int]:
    filters = [AiChangeRecord.committed_at >= since] if since is not None else []
    total = (
        await session.execute(
            select(func.count()).select_from(AiChangeRecord).where(*filters)
        )
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(AiChangeRecord)
                .where(*filters)
                .order_by(AiChangeRecord.committed_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_change_record_out(row) for row in rows], total


async def get_ai_change_record(
    session: AsyncSession, record_id: UUID
) -> AiChangeRecordOut | None:
    record = await session.get(AiChangeRecord, record_id)
    if record is None:
        return None
    return _change_record_out(record)


async def _find_by_commit_sha(session: AsyncSession, commit_sha: str) -> AiChangeRecord | None:
    return (
        await session.execute(
            select(AiChangeRecord).where(AiChangeRecord.commit_sha == commit_sha)
        )
    ).scalar_one_or_none()


async def create_ai_change_record(
    session: AsyncSession, data: AiChangeRecordCreate, *, author_user_id: UUID | None
) -> tuple[AiChangeRecordOut, bool]:
    """Returns (record, created). `created=False` means `commit_sha`
    already had a row — the *existing* row is returned unchanged, never a
    duplicate (docs/AI_NATIVE_PLAN.md Phase 21 Known Trap 4: a hook
    re-fire or a retried POST after a crashed response must be safe).

    The IntegrityError branch below is the same guarantee for the rarer
    case of two near-simultaneous requests for the same commit_sha racing
    each other: whichever loses the DB's own UNIQUE constraint still
    returns the winner's row instead of raising a 500."""
    existing = await _find_by_commit_sha(session, data.commit_sha)
    if existing is not None:
        return _change_record_out(existing), False

    record = AiChangeRecord(
        commit_sha=data.commit_sha,
        summary=data.summary,
        files_changed=data.files_changed,
        git_author=data.git_author,
        author_user_id=author_user_id,
        committed_at=data.committed_at,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _find_by_commit_sha(session, data.commit_sha)
        if existing is None:
            raise
        return _change_record_out(existing), False

    await session.refresh(record)
    return _change_record_out(record), True
