"""Request and response shapes for the divergence endpoint.

The *finding* shape is `culprit_model.facts.Divergence` itself, not a
copy — the same decision, for the same reason, as `app/facts/schemas.py`
makes about `CaptureBundle`. One definition, shared by the producer and
the consumer, with no second copy to drift from the first. It also means
the model's own validators run inside FastAPI's request validation: a
divergence whose two sides name different subjects, or whose facts carry
an ungranted config literal, is refused with a 422 before any
application code sees it.
"""

from datetime import datetime
from uuid import UUID

from culprit_model.facts import Divergence
from pydantic import BaseModel, Field


class DivergenceCapture(BaseModel):
    """One run's findings.

    `capture_id` is optional and, when given, must name a capture already
    stored by `POST /facts/captures`. Optional because the two uploads
    are independent: a team may want divergence history without keeping
    every fact set that produced it, and requiring the facts first would
    make the smaller, more useful upload depend on the larger one.
    """

    capture_id: UUID | None = None
    divergences: list[Divergence] = Field(default_factory=list)


class DivergencesAccepted(BaseModel):
    """What the caller gets back.

    `first_seen` and `seen_again` are reported separately because that is
    the question the endpoint exists to answer. "14 findings" says
    nothing; "2 new, 12 you already knew about" is the sentence a person
    reads on a deploy.
    """

    first_seen: int
    seen_again: int
    suppressed: int
    stored_at: datetime
