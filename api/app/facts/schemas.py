"""Response shapes for the capture endpoint.

The *request* shape is `culprit_model.protocol.CaptureBundle` itself,
not a copy of it. That is deliberate and is the point of the model
package existing: the CLI serialises a `CaptureBundle`, the API
deserialises the same class, and there is no second definition to drift
from the first. Copying it into a local pydantic model here would
reintroduce exactly the hand-mirroring `scripts/check_schema_drift.py`
had to be written to police elsewhere.

It also means the `Fact` validators come along — a bundle carrying an
ungranted config literal is rejected by FastAPI's own request validation
with a 422, before any application code runs.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CaptureAccepted(BaseModel):
    """What the caller gets back: enough to find the capture again, and
    an honest count of what was skipped.

    `skipped` is echoed rather than dropped because the CLI prints it and
    a CI log is where someone will read it. "Stored 214 facts, skipped
    client_calls because culprit-extract-node is not installed" is the
    line that gets an extractor installed.
    """

    capture_id: UUID
    plane: str
    extractor: str
    started_at: datetime
    finished_at: datetime
    facts_stored: int
    skipped: int
