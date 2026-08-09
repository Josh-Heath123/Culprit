from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ArchitectureDecisionCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)


class ArchitectureDecisionPatch(BaseModel):
    """Both fields optional; only the ones actually present are applied —
    same `exclude_unset=True` convention as `PostmortemPatch`."""

    title: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)


class ArchitectureDecisionOut(BaseModel):
    """`embedding_status` is derived from embedded_at/embedding_error, not
    a stored column — see service.py's `_embedding_status`. The raw
    1024-float embedding vector is never included here, same as
    `PostmortemOut`."""

    id: UUID
    title: str
    body: str
    author_user_id: UUID | None
    embedding_status: Literal["pending", "embedded", "failed"]
    embedding_error: str | None
    created_at: datetime | None
    updated_at: datetime | None


class PaginatedArchitectureDecisions(BaseModel):
    items: list[ArchitectureDecisionOut]
    limit: int
    offset: int
    total: int


class AiChangeRecordCreate(BaseModel):
    """The shape `.claude/hooks/capture_ai_change.sh` POSTs — every field
    here comes straight from `git log`/`git show`, never typed by a
    human (docs/AI_NATIVE_PLAN.md Phase 21's whole point: this must fill
    itself)."""

    commit_sha: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    files_changed: list[str] = Field(default_factory=list)
    git_author: str | None = None
    committed_at: datetime


class AiChangeRecordOut(BaseModel):
    id: UUID
    commit_sha: str
    summary: str
    files_changed: list[str]
    git_author: str | None
    author_user_id: UUID | None
    embedding_status: Literal["pending", "embedded", "failed"]
    embedding_error: str | None
    committed_at: datetime
    created_at: datetime | None


class PaginatedAiChangeRecords(BaseModel):
    items: list[AiChangeRecordOut]
    limit: int
    offset: int
    total: int
