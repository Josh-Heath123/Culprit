"""Response shapes for `/captures` (Phase 30)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from culprit_model.capture_diff import DiffEntry
from pydantic import BaseModel


class CaptureAccepted(BaseModel):
    capture_id: UUID
    environment: str
    #: The SHA-256 of the sealed payload, recomputed here.
    digest: str
    #: Key ids of the signatures that verified; null when unsigned. A
    #: verified signature says the capture is unaltered since that key
    #: signed it — not who holds the key.
    signed_by: str | None
    facts_stored: int
    refused: int


class CaptureFactOut(BaseModel):
    subject: str
    predicate: str
    #: Always a rendering: a config key's shape, never its value.
    value: str
    grant_ref: str | None
    extractor: str
    artefact: str | None


class CaptureDetail(BaseModel):
    capture_id: UUID
    environment: str
    extractor: str
    started_at: datetime
    finished_at: datetime | None
    digest: str | None
    signed_by: str | None
    #: What the capture was allowed to look at, and what it was refused —
    #: stored whole so a capture read back next month still says what it
    #: did not look at.
    grants: list[dict[str, Any]]
    refused: list[dict[str, Any]]
    facts: list[CaptureFactOut]


class CaptureDiff(BaseModel):
    """A snapshot diff of two stored captures — *not* the divergence engine.

    No severity, no INTENT, no absence judged against an enumerating
    source: those need the repository and run in the CLI (`culprit diff`).
    This says which answers differ and which exist on one side only.
    """

    a: UUID
    b: UUID
    a_environment: str
    b_environment: str
    entries: list[DiffEntry]
