"""Request and response shapes for `/readings` and `/probes`.

The reading shape is `culprit_model.readings.Reading` itself, not a copy
— the same decision `app/divergences/schemas.py` makes about
`Divergence`, for the same reason. One definition shared by the producer
and the consumer, and the model's own validators run inside FastAPI's
request validation: a reading whose `target` is not a subject URI, whose
`inconclusive` verdict carries no reason, or whose evidence is
credential-shaped and unredacted is refused with a 422 before any
application code sees it.
"""

from datetime import datetime

from culprit_model.readings import ProbeManifest, Reading
from pydantic import BaseModel, Field


class ReadingBatch(BaseModel):
    """One agent's readings from one run.

    No capture id. A reading is not part of a snapshot the way a fact is
    — it is a measurement at a moment, and `taken_at` already says which
    moment. Grouping readings into runs is a Phase 33 question, once
    there is an agent whose runs are a thing to group by.
    """

    readings: list[Reading] = Field(default_factory=list)


class ReadingsAccepted(BaseModel):
    """What the caller gets back.

    `duplicates` is reported rather than silently absorbed: a probe
    runner that retries a partially-delivered batch should be able to see
    that the retry was the reason nothing new landed.
    """

    stored: int
    duplicates: int
    stored_at: datetime


class ProbeCatalogue(BaseModel):
    """Every probe this build knows how to describe."""

    probes: list[ProbeManifest]


class ProbeRunUnavailable(BaseModel):
    """Why `POST /probes/{id}/run` did not run anything.

    Structured rather than a bare message string, because the useful part
    is the command: a caller that wanted a measurement can copy
    `run_locally` and have one. `available_from` names the phase that
    changes the answer, so nobody reads the 503 as a transient outage and
    retries it forever.
    """

    probe_id: str
    reason: str
    run_locally: str
    available_from: str
