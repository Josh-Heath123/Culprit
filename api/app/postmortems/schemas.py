from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PostmortemCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    incident_id: UUID | None = None


class PostmortemPatch(BaseModel):
    """Both fields optional, and an entirely empty patch (`{}`) is valid —
    that's exactly what the frontend's "retry" action sends on a failed
    postmortem to re-enqueue embedding without changing any content (see
    app/postmortems/service.py::patch_postmortem)."""

    title: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)


class PostmortemOut(BaseModel):
    """`embedding_status` is derived from embedded_at/embedding_error, not
    a stored column — see service.py's _embedding_status. The raw
    1024-float embedding vector is never included here."""

    id: UUID
    title: str
    body: str
    incident_id: UUID | None
    author_user_id: UUID | None
    embedding_status: Literal["pending", "embedded", "failed"]
    embedding_error: str | None
    created_at: datetime | None
    updated_at: datetime | None


class PaginatedPostmortems(BaseModel):
    items: list[PostmortemOut]
    limit: int
    offset: int
    total: int
