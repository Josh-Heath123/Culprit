"""Ingest API keys and the Phase 19 topology-suggestion queue — the two
things in the registry that were never part of the system model itself.

**What this module used to be.** Until Phase 30 it also held the
pre-Phase-27 `/services` surface re-expressed over `components`/
`connections`: a service's `depends_on` list translated to and from http
connections, so a client that only spoke the old shape kept working for
one release (Phase 27 field 9). Phase 30 field 6 removed that alias, and
the translation went with it — it could never express a connection's
kind or criticality, and it flattened `declared_by` on write
(docs/LIMITS.md recorded both). What is left is what nothing in
`app/model/` covers, served under `/model` by `app/model/router.py`.

Writes go through the `registry-admin` engine, reads through
`api-reader` — the same split this module has always had, and the same
roles, so moving the endpoints widened nothing.
"""

from datetime import UTC, datetime
from uuid import UUID

from culprit_model.graph import ConnectionKind, Criticality, DeclaredBy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import ApiKey, Component, Connection, ObservedServiceEdge
from app.registry.keys import generate_api_key, hash_api_key
from app.registry.schemas import KeyCreate, TopologyEdgeRef, TopologySuggestionOut

#: The connection kind an accepted suggestion becomes. Topology inference
#: reads `CLIENT` spans (Phase 19, Option A) — an outbound call, which in
#: every instrumented service this has run against is HTTP. An operator
#: who knows better reclassifies it with `PATCH /model/connections/{id}`,
#: which preserves `declared_by = accepted_suggestion`.
_SUGGESTED_KIND = str(ConnectionKind.HTTP)


class UnknownEdge(Exception):
    """No observed_service_edges row for this (from_service, to_service)
    pair — the admin is acting on a suggestion that either never existed
    or has already been dismissed/accepted."""

    def __init__(self, from_service: str, to_service: str) -> None:
        self.from_service = from_service
        self.to_service = to_service
        super().__init__(f"no observed edge {from_service!r} -> {to_service!r}")


class UnregisteredEndpoint(Exception):
    """Raised by accept_topology_suggestion when either endpoint of the
    edge isn't a registered component — docs/SELF_HOSTED_PLAN.md Phase 19,
    Known Trap 2: refuse clearly rather than silently half-registering a
    component with no API key, which is explicitly called out as the worst
    of the available options."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"not a registered component: {', '.join(sorted(names))}")


async def create_key(
    session: AsyncSession, component_id: UUID, data: KeyCreate
) -> tuple[ApiKey, str] | None:
    """Issues another ingest key for a component. `None` if it does not
    exist. The column is still `api_keys.service_id` — Phase 27 renamed
    the table it points at, not the FK (docs/LIMITS.md)."""
    name = (
        await session.execute(select(Component.name).where(Component.id == component_id))
    ).scalar_one_or_none()
    if name is None:
        return None
    plaintext = generate_api_key()
    key = ApiKey(
        service_id=component_id,
        service_name=name,
        key_hash=hash_api_key(plaintext),
        label=data.label,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key, plaintext


async def revoke_key(session: AsyncSession, component_id: UUID, key_id: UUID) -> bool:
    """Revokes, never deletes: `last_used_at` on a revoked key is how an
    operator finds out whether a leaked key was used before they caught
    it. Scoped to the component so a key id from one component's row
    cannot revoke another's."""
    key = (
        await session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.service_id == component_id)
        )
    ).scalar_one_or_none()
    if key is None:
        return False
    key.revoked_at = datetime.now(UTC)
    await session.commit()
    return True


# --- Phase 19 topology suggestions ------------------------------------


async def _already_declared_pairs(session: AsyncSession) -> set[tuple[str, str]]:
    """Every (from_name, to_name) already connected, by name —
    observed_service_edges stores names, not FKs (an edge can
    legitimately point at a component Culprit hasn't registered), so
    comparing against declared connections has to go through Component
    twice, once per side of the directed edge.

    Every connection kind counts, not just http: if a `sql` connection
    already records that these two are joined, re-suggesting the pair
    would be asking the admin to declare something the model already
    knows.
    """
    from_component = aliased(Component)
    to_component = aliased(Component)
    rows = (
        await session.execute(
            select(from_component.name, to_component.name)
            .select_from(Connection)
            .join(from_component, from_component.id == Connection.from_component_id)
            .join(to_component, to_component.id == Connection.to_component_id)
        )
    ).all()
    return {(row[0], row[1]) for row in rows}


async def list_topology_suggestions(session: AsyncSession) -> list[TopologySuggestionOut]:
    """Observed edges that are neither dismissed nor already declared,
    ordered by observation count descending — docs/SELF_HOSTED_PLAN.md
    Phase 19 step 3. Nothing here changes correlation; that only happens
    on accept_topology_suggestion below."""
    edges = (
        (
            await session.execute(
                select(ObservedServiceEdge)
                .where(ObservedServiceEdge.dismissed_at.is_(None))
                .order_by(ObservedServiceEdge.observations.desc())
            )
        )
        .scalars()
        .all()
    )
    if not edges:
        return []

    declared = await _already_declared_pairs(session)
    edges = [e for e in edges if (e.from_service, e.to_service) not in declared]
    if not edges:
        return []

    names = {name for edge in edges for name in (edge.from_service, edge.to_service)}
    registered = set(
        (await session.execute(select(Component.name).where(Component.name.in_(names))))
        .scalars()
        .all()
    )

    return [
        TopologySuggestionOut(
            from_service=edge.from_service,
            to_service=edge.to_service,
            observations=edge.observations,
            first_seen_at=edge.first_seen_at,
            last_seen_at=edge.last_seen_at,
            from_service_registered=edge.from_service in registered,
            to_service_registered=edge.to_service in registered,
        )
        for edge in edges
    ]


async def _get_observed_edge(
    session: AsyncSession, edge: TopologyEdgeRef
) -> ObservedServiceEdge | None:
    return (
        await session.execute(
            select(ObservedServiceEdge).where(
                ObservedServiceEdge.from_service == edge.from_service,
                ObservedServiceEdge.to_service == edge.to_service,
            )
        )
    ).scalar_one_or_none()


async def accept_topology_suggestion(session: AsyncSession, edge: TopologyEdgeRef) -> None:
    """Inserts a `connections` row — the only thing that actually changes
    correlation behaviour; observed_service_edges itself is left alone
    (no "accepted" flag exists or is needed: once declared, the pair is
    filtered out of list_topology_suggestions by _already_declared_pairs
    on the next call).

    The new row is `declared_by = accepted_suggestion`, which the old
    schema had no way to record. That distinction is why the column
    exists: a human accepting a machine's proposal is different evidence
    from a human writing the edge down unprompted, and `apply_model.py`
    relies on it — an accepted suggestion is not removed by a
    `culprit.yaml` that does not mention it.
    """
    if await _get_observed_edge(session, edge) is None:
        raise UnknownEdge(edge.from_service, edge.to_service)

    rows = (
        await session.execute(
            select(Component.id, Component.name).where(
                Component.name.in_([edge.from_service, edge.to_service])
            )
        )
    ).all()
    id_by_name = {name: id_ for id_, name in rows}
    missing = [name for name in (edge.from_service, edge.to_service) if name not in id_by_name]
    if missing:
        raise UnregisteredEndpoint(missing)

    existing = (
        await session.execute(
            select(Connection.id).where(
                Connection.from_component_id == id_by_name[edge.from_service],
                Connection.to_component_id == id_by_name[edge.to_service],
                Connection.kind == _SUGGESTED_KIND,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Connection(
                from_component_id=id_by_name[edge.from_service],
                to_component_id=id_by_name[edge.to_service],
                kind=_SUGGESTED_KIND,
                declared_by=str(DeclaredBy.ACCEPTED_SUGGESTION),
                criticality=str(Criticality.UNKNOWN),
            )
        )
    await session.commit()


async def dismiss_topology_suggestion(session: AsyncSession, edge: TopologyEdgeRef) -> bool:
    observed = await _get_observed_edge(session, edge)
    if observed is None:
        return False
    observed.dismissed_at = datetime.now(UTC)
    await session.commit()
    return True


__all__ = [
    "UnknownEdge",
    "UnregisteredEndpoint",
    "accept_topology_suggestion",
    "create_key",
    "dismiss_topology_suggestion",
    "list_topology_suggestions",
    "revoke_key",
]
