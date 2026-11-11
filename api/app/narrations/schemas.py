"""The narration as the investigation page shows it."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NarrationSegment(BaseModel):
    """A run of the prose: plain text, or — with `evidence` — a citation,
    replaced by that evidence item's own text from the record."""

    text: str
    evidence: int | None = None


class NarrationView(BaseModel):
    #: off: no provider is configured. not_narrated: one is, and no attempt
    #: has finished. complete, failed, refused: the newest attempt's final
    #: status. Never pending.
    state: Literal["off", "not_narrated", "complete", "failed", "refused"]
    attempts: int
    max_attempts: int
    provider: str | None = None
    model: str | None = None
    narrated_at: datetime | None = None
    #: complete only: the prose, checked again before it is served.
    segments: list[NarrationSegment] | None = None
    #: failed only: why, redacted.
    reason: str | None = None
    #: refused only: what the prose named that the investigation does not.
    named: list[str] | None = None
