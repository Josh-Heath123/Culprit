"""The pre-Phase-27 `/services` surface, re-expressed over the system
model, plus the two things that were never part of the model itself:
ingest API keys and the Phase 19 topology-suggestion queue.

**What this module is now.** Phase 27 replaced `services`/
`service_dependencies` with `components`/`connections` (see
`api/app/model/`). The frontend and `docs/INSTRUMENTATION.md` both point
at `/services`, so that surface is retained for one release as a thin
translation layer and removed in Phase 30 (Phase 27, field 9). Every
component/connection write below delegates to `app.model.service` — this
is a different *shape* over the same logic, never a second
implementation of what a component is.

The translation that matters: a service's `depends_on` list is a set of
**http connections** out of that component. That is what
`service_dependencies` meant, and it is what the data migration produced,
so a client that only ever spoke the old shape keeps seeing exactly the
edges it declared. A connection of any other kind is invisible through
this surface, by construction — the old shape has nowhere to put it. That
is a documented limit (docs/LIMITS.md), not a silent one, and it is the
reason the alias is temporary.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from culprit_model.canonical import canonical_component
from culprit_model.graph import ComponentKind, ConnectionKind, Criticality, DeclaredBy
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.db.models import ApiKey, Component, Connection, ObservedServiceEdge
from app.model.schemas import ComponentCreate, ComponentPatch
from app.model.service import (
    ComponentNameTaken,
    UnknownComponentName,
    create_component,
    delete_component,
    patch_component,
)
from app.registry.keys import generate_api_key, hash_api_key
from app.registry.schemas import (
    KeyCreate,
    KeyOut,
    ServiceCreate,
    ServiceOut,
    ServicePatch,
    TopologyEdgeRef,
    TopologySuggestionOut,
)

#: The connection kind `depends_on` means. Everything on this surface is
#: HTTP because `service_dependencies` had no kind and the migration gave
#: every migrated row `http`.
_LEGACY_KIND = str(ConnectionKind.HTTP)


class ServiceNameTaken(ComponentNameTaken):
    """Kept as its own name because `app/registry/router.py` catches it
    and turns it into a 409. A subclass, not a copy, so a caller that
    catches either gets the same behaviour."""


class UnknownDependency(Exception):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"unknown service name(s) in depends_on: {', '.join(sorted(names))}")


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
        super().__init__(f"not a registered service: {', '.join(sorted(names))}")


def _key_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        label=key.label,
        created_at=key.created_at,  # type: ignore[arg-type]
        last_used_at=key.last_used_at,
        revoked=key.revoked_at is not None,
    )


def _service_out(component: Component, depends_on: list[str]) -> ServiceOut:
    return ServiceOut(
        id=component.id,
        name=component.name,
        display_name=component.display_name,
        sort_order=component.sort_order,
        monitored_metrics=component.monitored_metrics,
        disabled=component.disabled_at is not None,
        depends_on=sorted(depends_on),
        keys=[_key_out(k) for k in component.api_keys],
        created_at=component.created_at,
    )


async def _get_component_orm(session: AsyncSession, component_id: UUID) -> Component | None:
    return (
        await session.execute(
            select(Component)
            .options(selectinload(Component.api_keys))
            .where(Component.id == component_id)
        )
    ).scalar_one_or_none()


async def _resolve_dependency_ids(session: AsyncSession, names: list[str]) -> list[UUID]:
    """Every name must already be a registered component — unlike the
    demo-seeding migration (which silently skips unknown names because
    it's reproducing fixed historical behaviour), this is a live admin
    API call, so an unknown dependency name is reported, not dropped."""
    if not names:
        return []
    canonical = [canonical_component(name) for name in names]
    rows = (
        await session.execute(
            select(Component.id, Component.name).where(Component.name.in_(canonical))
        )
    ).all()
    found_by_name = {name: id_ for id_, name in rows}
    missing = [name for name in canonical if name not in found_by_name]
    if missing:
        raise UnknownDependency(missing)
    return [found_by_name[name] for name in canonical]


async def _depends_on_for(session: AsyncSession, component_id: UUID) -> list[str]:
    rows = (
        await session.execute(
            select(Component.name)
            .join(Connection, Connection.to_component_id == Component.id)
            .where(
                Connection.from_component_id == component_id,
                Connection.kind == _LEGACY_KIND,
            )
        )
    ).scalars()
    return list(rows)


async def list_services(session: AsyncSession) -> list[ServiceOut]:
    components = (
        (
            await session.execute(
                select(Component)
                .options(selectinload(Component.api_keys))
                .order_by(Component.sort_order, Component.name)
            )
        )
        .scalars()
        .all()
    )

    id_to_name = {c.id: c.name for c in components}
    edges = (
        await session.execute(
            select(Connection.from_component_id, Connection.to_component_id).where(
                Connection.kind == _LEGACY_KIND
            )
        )
    ).all()
    deps_by_from: dict[UUID, list[str]] = defaultdict(list)
    for from_id, to_id in edges:
        to_name = id_to_name.get(to_id)
        if to_name is not None:
            deps_by_from[from_id].append(to_name)

    return [_service_out(c, deps_by_from.get(c.id, [])) for c in components]


async def get_service(session: AsyncSession, service_id: UUID) -> ServiceOut | None:
    component = await _get_component_orm(session, service_id)
    if component is None:
        return None
    return _service_out(component, await _depends_on_for(session, service_id))


async def create_service(session: AsyncSession, data: ServiceCreate) -> tuple[ServiceOut, str]:
    dep_ids = await _resolve_dependency_ids(session, data.depends_on)
    try:
        component, plaintext = await create_component(
            session,
            ComponentCreate(
                name=data.name,
                display_name=data.display_name,
                # Everything created through the legacy surface is a
                # service: the old shape had no way to say otherwise, and
                # guessing a kind from the name would be a fabrication.
                kind=ComponentKind.SERVICE,
                monitored_metrics=data.monitored_metrics,
            ),
        )
    except ComponentNameTaken as exc:
        raise ServiceNameTaken(exc.name) from exc

    for dep_id in dep_ids:
        session.add(_legacy_connection(component.id, dep_id))
    await session.commit()

    out = await get_service(session, component.id)
    assert out is not None
    return out, plaintext


def _legacy_connection(from_id: UUID, to_id: UUID) -> Connection:
    """An edge declared through the old surface.

    `declared_by = culprit_yaml` because that is what
    `service_dependencies` always meant — a human declared it — and
    matching the data migration keeps a hand-declared edge and a migrated
    one indistinguishable, which they are. `criticality = unknown`
    because nothing on this surface can say otherwise; see
    `Criticality`'s own docstring on why that is the honest value.
    """
    return Connection(
        from_component_id=from_id,
        to_component_id=to_id,
        kind=_LEGACY_KIND,
        declared_by=str(DeclaredBy.CULPRIT_YAML),
        criticality=str(Criticality.UNKNOWN),
    )


async def patch_service(
    session: AsyncSession, service_id: UUID, patch: ServicePatch
) -> ServiceOut | None:
    component = await _get_component_orm(session, service_id)
    if component is None:
        return None

    fields = patch.model_dump(exclude_unset=True)

    # Resolve dependency names BEFORE touching the component, matching
    # create_service. patch_component commits internally, so validating
    # afterwards would leave a PATCH carrying both `display_name` and a
    # typo'd `depends_on` returning 400 with the display name already
    # written — a half-applied PATCH the pre-Phase-27 implementation
    # could not produce, because it committed exactly once at the end.
    dep_ids = (
        await _resolve_dependency_ids(session, fields["depends_on"])
        if "depends_on" in fields
        else None
    )

    component_fields = {
        key: fields[key]
        for key in ("display_name", "sort_order", "monitored_metrics", "disabled")
        if key in fields
    }
    if component_fields:
        await patch_component(session, service_id, ComponentPatch(**component_fields))

    if dep_ids is not None:
        # Only http connections are rewritten. A sql or message edge into
        # the same component was never expressible through this surface,
        # so a legacy PATCH must not silently delete one.
        await session.execute(
            delete(Connection).where(
                Connection.from_component_id == service_id,
                Connection.kind == _LEGACY_KIND,
            )
        )
        for dep_id in dep_ids:
            session.add(_legacy_connection(service_id, dep_id))
        await session.commit()

    return await get_service(session, service_id)


async def delete_service(session: AsyncSession, service_id: UUID, *, purge: bool) -> bool:
    return await delete_component(session, service_id, purge=purge)


async def create_key(
    session: AsyncSession, service_id: UUID, data: KeyCreate
) -> tuple[ApiKey, str] | None:
    name = (
        await session.execute(select(Component.name).where(Component.id == service_id))
    ).scalar_one_or_none()
    if name is None:
        return None
    plaintext = generate_api_key()
    key = ApiKey(
        service_id=service_id,
        service_name=name,
        key_hash=hash_api_key(plaintext),
        label=data.label,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key, plaintext


async def revoke_key(session: AsyncSession, service_id: UUID, key_id: UUID) -> bool:
    key = (
        await session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.service_id == service_id)
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
                Connection.kind == _LEGACY_KIND,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Connection(
                from_component_id=id_by_name[edge.from_service],
                to_component_id=id_by_name[edge.to_service],
                kind=_LEGACY_KIND,
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
    "ServiceNameTaken",
    "UnknownComponentName",
    "UnknownDependency",
    "UnknownEdge",
    "UnregisteredEndpoint",
    "accept_topology_suggestion",
    "create_key",
    "create_service",
    "delete_service",
    "dismiss_topology_suggestion",
    "get_service",
    "list_services",
    "list_topology_suggestions",
    "patch_service",
    "revoke_key",
]
