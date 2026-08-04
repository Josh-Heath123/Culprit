from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RawEventIn(BaseModel):
    """The raw_events row shape (Phase 1 schema), normalized from OTLP.

    Written by api/app/ingest_gateway (constructs and serializes these
    onto the Redis Stream) and read by worker/app/consumer.py (validates
    incoming stream entries against this same model before insert) —
    one definition instead of the two hand-reimplemented copies that
    used to drift independently.
    """

    time: datetime
    service_name: str
    event_type: Literal["metric", "log"]
    metric_name: str | None = None
    value: float | None = None
    message: str | None = None
    attributes: dict = Field(default_factory=dict)
