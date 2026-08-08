"""DB access for the service registry — the registry-admin role for
writes, whatever engine the caller passes for reads (api/app/main.py
wires api-reader for GET /services, registry-admin for everything else;
see that module's lifespan). Transform logic (ORM row -> ServiceOut) lives
here too, not a separate transforms.py — this package is small enough
that the split app/incidents/ uses would just be indirection.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.db.models import ApiKey, ObservedServiceEdge, Service, ServiceDependency
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


class ServiceNameTaken(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a service named {name!r} already exists")


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
    edge isn't a registered service — docs/SELF_HOSTED_PLAN.md Phase 19,
    Known Trap 2: refuse clearly rather than silently half-registering a
    service with no API key, which is explicitly called out as the worst
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


def _service_out(service: Service, depends_on: list[str]) -> ServiceOut:
    return ServiceOut(
        id=service.id,
        name=service.name,
        display_name=service.display_name,
        sort_order=service.sort_order,
        monitored_metrics=service.monitored_metrics,
        disabled=service.disabled_at is not None,
        depends_on=sorted(depends_on),
        keys=[_key_out(k) for k in service.api_keys],
        created_at=service.created_at,
    )


async def _resolve_dependency_ids(session: AsyncSession, names: list[str]) -> list[UUID]:
    """Every name in `names` must already be a registered service — unlike
    the demo-seeding migration (which silently skips unknown names because
    it's reproducing fixed historical behaviour), this is a live admin API
    call, so an unknown dependency name is reported back, not dropped
    silently."""
    if not names:
        return []
    rows = (
        await session.execute(select(Service.id, Service.name).where(Service.name.in_(names)))
    ).all()
    found_by_name = {name: id_ for id_, name in rows}
    missing = [name for name in names if name not in found_by_name]
    if missing:
        raise UnknownDependency(missing)
    return [found_by_name[name] for name in names]


async def _get_service_orm(session: AsyncSession, service_id: UUID) -> Service | None:
    return (
        await session.execute(
            select(Service).options(selectinload(Service.api_keys)).where(Service.id == service_id)
        )
    ).scalar_one_or_none()


async def _depends_on_for(session: AsyncSession, service_id: UUID) -> list[str]:
    rows = (
        await session.execute(
            select(Service.name)
            .join(ServiceDependency, ServiceDependency.to_service_id == Service.id)
            .where(ServiceDependency.from_service_id == service_id)
        )
    ).scalars()
    return list(rows)


async def list_services(session: AsyncSession) -> list[ServiceOut]:
    services = (
        await session.execute(
            select(Service)
            .options(selectinload(Service.api_keys))
            .order_by(Service.sort_order, Service.name)
        )
    ).scalars().all()

    id_to_name = {s.id: s.name for s in services}
    dep_rows = (
        await session.execute(
            select(ServiceDependency.from_service_id, ServiceDependency.to_service_id)
        )
    ).all()
    deps_by_from: dict[UUID, list[str]] = defaultdict(list)
    for from_id, to_id in dep_rows:
        to_name = id_to_name.get(to_id)
        if to_name is not None:
            deps_by_from[from_id].append(to_name)

    return [_service_out(s, deps_by_from.get(s.id, [])) for s in services]


async def get_service(session: AsyncSession, service_id: UUID) -> ServiceOut | None:
    service = await _get_service_orm(session, service_id)
    if service is None:
        return None
    return _service_out(service, await _depends_on_for(session, service_id))


async def create_service(session: AsyncSession, data: ServiceCreate) -> tuple[ServiceOut, str]:
    existing = (
        await session.execute(select(Service.id).where(Service.name == data.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise ServiceNameTaken(data.name)

    dep_ids = await _resolve_dependency_ids(session, data.depends_on)

    service = Service(
        name=data.name,
        display_name=data.display_name,
        monitored_metrics=data.monitored_metrics,
    )
    session.add(service)
    await session.flush()

    for dep_id in dep_ids:
        session.add(ServiceDependency(from_service_id=service.id, to_service_id=dep_id))

    plaintext = generate_api_key()
    session.add(
        ApiKey(
            service_name=service.name,
            service_id=service.id,
            key_hash=hash_api_key(plaintext),
            label="initial",
        )
    )

    await session.commit()
    out = await get_service(session, service.id)
    assert out is not None
    return out, plaintext


async def patch_service(
    session: AsyncSession, service_id: UUID, patch: ServicePatch
) -> ServiceOut | None:
    service = await _get_service_orm(session, service_id)
    if service is None:
        return None

    fields = patch.model_dump(exclude_unset=True)

    if "display_name" in fields:
        service.display_name = fields["display_name"]
    if "sort_order" in fields:
        service.sort_order = fields["sort_order"]
    if "monitored_metrics" in fields:
        service.monitored_metrics = fields["monitored_metrics"]
    if "disabled" in fields:
        service.disabled_at = datetime.now(UTC) if fields["disabled"] else None
    if "depends_on" in fields:
        dep_ids = await _resolve_dependency_ids(session, fields["depends_on"])
        existing_edges = (
            await session.execute(
                select(ServiceDependency).where(ServiceDependency.from_service_id == service_id)
            )
        ).scalars().all()
        for edge in existing_edges:
            await session.delete(edge)
        for dep_id in dep_ids:
            session.add(ServiceDependency(from_service_id=service_id, to_service_id=dep_id))

    await session.commit()
    return await get_service(session, service_id)


async def delete_service(session: AsyncSession, service_id: UUID, *, purge: bool) -> bool:
    """Soft delete (default) sets disabled_at only — every historical
    raw_events/anomalies/incident_candidates row survives, and so does the
    service row itself. `purge=True` hard-deletes the service row (and,
    via the FKs' ON DELETE CASCADE, its api_keys and service_dependencies
    edges) but still never touches telemetry tables — raw_events has no
    FK to services at all, on purpose (see api/app/db/models.py's
    RawEvent docstring on why hypertables don't get FKs in this project).
    """
    if purge:
        # A plain Core DELETE, not session.delete(service) on the loaded
        # ORM object: the ORM's unit-of-work nulls a loaded collection's
        # FK before deleting the parent (it did here, since api_keys is
        # already eager-loaded elsewhere in this module) — service_id is
        # NOT NULL, so that null-out fails outright. A Core statement
        # skips ORM relationship handling entirely and lets the FKs' own
        # ON DELETE CASCADE do the actual work, which is what's wanted
        # here regardless.
        existing = (
            await session.execute(select(Service.id).where(Service.id == service_id))
        ).scalar_one_or_none()
        if existing is None:
            return False
        await session.execute(delete(Service).where(Service.id == service_id))
        await session.commit()
        return True

    service = await _get_service_orm(session, service_id)
    if service is None:
        return False
    service.disabled_at = datetime.now(UTC)
    await session.commit()
    return True


async def create_key(
    session: AsyncSession, service_id: UUID, data: KeyCreate
) -> tuple[ApiKey, str] | None:
    service = (
        await session.execute(select(Service.name).where(Service.id == service_id))
    ).scalar_one_or_none()
    if service is None:
        return None
    plaintext = generate_api_key()
    key = ApiKey(
        service_id=service_id,
        service_name=service,
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


async def _already_declared_pairs(session: AsyncSession) -> set[tuple[str, str]]:
    """Every (from_name, to_name) already in service_dependencies, by
    name — observed_service_edges stores names, not FKs (an edge can
    legitimately point at a service Culprit hasn't registered), so
    comparing against declared dependencies has to go through Service
    twice, once per side of the directed edge."""
    from_service = aliased(Service)
    to_service = aliased(Service)
    rows = (
        await session.execute(
            select(from_service.name, to_service.name)
            .select_from(ServiceDependency)
            .join(from_service, from_service.id == ServiceDependency.from_service_id)
            .join(to_service, to_service.id == ServiceDependency.to_service_id)
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

    service_names = {name for edge in edges for name in (edge.from_service, edge.to_service)}
    registered = set(
        (await session.execute(select(Service.name).where(Service.name.in_(service_names))))
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
    """Inserts into service_dependencies — the only thing that actually
    changes correlation behaviour; observed_service_edges itself is left
    alone (no "accepted" flag exists or is needed: once declared, the
    pair is filtered out of list_topology_suggestions by
    _already_declared_pairs on the next call)."""
    if await _get_observed_edge(session, edge) is None:
        raise UnknownEdge(edge.from_service, edge.to_service)

    rows = (
        await session.execute(
            select(Service.id, Service.name).where(
                Service.name.in_([edge.from_service, edge.to_service])
            )
        )
    ).all()
    id_by_name = {name: id_ for id_, name in rows}
    missing = [name for name in (edge.from_service, edge.to_service) if name not in id_by_name]
    if missing:
        raise UnregisteredEndpoint(missing)

    existing = (
        await session.execute(
            select(ServiceDependency).where(
                ServiceDependency.from_service_id == id_by_name[edge.from_service],
                ServiceDependency.to_service_id == id_by_name[edge.to_service],
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ServiceDependency(
                from_service_id=id_by_name[edge.from_service],
                to_service_id=id_by_name[edge.to_service],
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
