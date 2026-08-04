from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RawEventIn(BaseModel):
    """The raw_events row shape (Phase 1 schema), normalized from OTLP."""

    time: datetime
    service_name: str
    event_type: Literal["metric", "log"]
    metric_name: str | None = None
    value: float | None = None
    message: str | None = None
    attributes: dict = Field(default_factory=dict)
