"""DB access for the postmortem write path (Phase 18) — the
postmortem-writer role for writes, whatever engine the caller passes for
reads (api/app/main.py wires api-reader for GET /postmortems,
postmortem-writer for everything else; see that module's lifespan).
Transform logic (ORM row -> PostmortemOut) lives here too, not a separate
transforms.py — same reasoning as app/registry/service.py's module
docstring: this package is small enough that the split app/incidents/
uses would just be indirection.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IncidentCandidate, Postmortem
from app.postmortems.schemas import PostmortemCreate, PostmortemOut, PostmortemPatch

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: GET /postmortems (list view) truncates body; GET /postmortems/{id}
#: (detail view) returns it in full — per docs/SELF_HOSTED_PLAN.md
#: Phase 18's API surface.
LIST_BODY_TRUNCATE_CHARS = 280


class UnknownIncident(Exception):
    def __init__(self, incident_id: UUID) -> None:
        self.incident_id = incident_id
        super().__init__(f"no incident with id {incident_id}")


def _embedding_status(postmortem: Postmortem) -> Literal["pending", "embedded", "failed"]:
    # Checked in this order deliberately: a postmortem can have a stale
    # (pre-edit) embedding *and* a fresh embedding_error at the same time
    # -- embed_job.py only overwrites `embedding`/`embedded_at` on
    # success, so a failed re-embed after editing the body leaves the old
    # vector in place rather than losing retrievability outright over a
    # transient rate-limit blip. That stale embedding must not read as
    # "embedded" while embedding_error is set, since the current body no
    # longer matches what was actually embedded.
    if postmortem.embedding_error is not None:
        return "failed"
    if postmortem.embedded_at is not None:
        return "embedded"
    return "pending"


def _postmortem_out(postmortem: Postmortem, *, truncate_body: bool = False) -> PostmortemOut:
    body = postmortem.body
    if truncate_body and len(body) > LIST_BODY_TRUNCATE_CHARS:
        body = body[:LIST_BODY_TRUNCATE_CHARS].rstrip() + "…"
    return PostmortemOut(
        id=postmortem.id,
        title=postmortem.title,
        body=body,
        incident_id=postmortem.incident_candidate_id,
        author_user_id=postmortem.author_user_id,
        embedding_status=_embedding_status(postmortem),
        embedding_error=postmortem.embedding_error,
        created_at=postmortem.created_at,
        updated_at=postmortem.updated_at,
    )


async def list_postmortems(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[PostmortemOut], int]:
    total = (await session.execute(select(func.count()).select_from(Postmortem))).scalar_one()
    rows = (
        (
            await session.execute(
                select(Postmortem).order_by(Postmortem.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_postmortem_out(row, truncate_body=True) for row in rows], total


async def get_postmortem(session: AsyncSession, postmortem_id: UUID) -> PostmortemOut | None:
    postmortem = await session.get(Postmortem, postmortem_id)
    if postmortem is None:
        return None
    return _postmortem_out(postmortem)


async def create_postmortem(
    session: AsyncSession, data: PostmortemCreate, *, author_user_id: UUID
) -> PostmortemOut:
    if data.incident_id is not None:
        exists = (
            await session.execute(
                select(IncidentCandidate.id).where(IncidentCandidate.id == data.incident_id)
            )
        ).scalar_one_or_none()
        if exists is None:
            raise UnknownIncident(data.incident_id)

    postmortem = Postmortem(
        title=data.title,
        body=data.body,
        incident_candidate_id=data.incident_id,
        author_user_id=author_user_id,
    )
    session.add(postmortem)
    await session.commit()
    await session.refresh(postmortem)
    return _postmortem_out(postmortem)


async def patch_postmortem(
    session: AsyncSession, postmortem_id: UUID, patch: PostmortemPatch
) -> tuple[PostmortemOut, bool] | None:
    """Returns (updated postmortem, should_reembed). A postmortem's
    embedding is computed from `body` alone (worker/scripts/seed_postmortems.py
    calls embed_document(seed.body); the *query* side embeds a rendered
    incident summary instead, via worker/app/rag/context.py's
    render_embedding_text — the two are deliberately asymmetric), so
    re-embedding is only triggered by an actual body change, *or* by a
    retry on an already-failed postmortem (embedding_error is not None) —
    including a title-only or entirely empty patch, which is exactly what
    the frontend's "retry" action sends. A title-only edit on a
    healthy (embedded/pending) postmortem must not re-embed."""
    postmortem = await session.get(Postmortem, postmortem_id)
    if postmortem is None:
        return None

    fields = patch.model_dump(exclude_unset=True)
    body_changed = "body" in fields and fields["body"] != postmortem.body
    should_reembed = body_changed or postmortem.embedding_error is not None

    if "title" in fields:
        postmortem.title = fields["title"]
    if "body" in fields:
        postmortem.body = fields["body"]
    if fields:
        postmortem.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(postmortem)
    return _postmortem_out(postmortem), should_reembed


async def delete_postmortem(session: AsyncSession, postmortem_id: UUID) -> bool:
    """root_cause_evidence on any incident that cited this postmortem is a
    JSONB snapshot (postmortem_id/postmortem_title/passage), not a live
    join — see api/app/db/models.py's IncidentCandidate docstring — so
    deleting a cited postmortem never breaks that incident's detail view;
    only the frontend's link to this now-404ing postmortem needs to
    degrade gracefully (see Evidence.tsx)."""
    postmortem = await session.get(Postmortem, postmortem_id)
    if postmortem is None:
        return False
    await session.delete(postmortem)
    await session.commit()
    return True
