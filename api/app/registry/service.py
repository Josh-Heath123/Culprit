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
from sqlalchemy.orm import selectinload

from app.db.models import ApiKey, Service, ServiceDependency
from app.registry.keys import generate_api_key, hash_api_key
from app.registry.schemas import KeyCreate, KeyOut, ServiceCreate, ServiceOut, ServicePatch


class ServiceNameTaken(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a service named {name!r} already exists")


class UnknownDependency(Exception):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"unknown service name(s) in depends_on: {', '.join(sorted(names))}")


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
