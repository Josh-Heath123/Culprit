"""Service registry admin API (Phase 14) — mounted at /services in
api/app/main.py, gated by the same require_auth dependency
app/incidents/router.py uses (Phase 16 upgrades this to require_admin
without changing any path, per docs/SELF_HOSTED_PLAN.md).

Reads use the api-reader engine already in app.state (read-only, same
one app/incidents/router.py uses); writes use a second, registry-admin
engine — see app/main.py's lifespan and app/registry/config.py.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from app.registry.schemas import (
    KeyCreate,
    KeyCreateResponse,
    ServiceCreate,
    ServiceCreateResponse,
    ServiceOut,
    ServicePatch,
    ServicesOut,
)
from app.registry.service import (
    ServiceNameTaken,
    UnknownDependency,
    create_key,
    create_service,
    delete_service,
    get_service,
    list_services,
    patch_service,
    revoke_key,
)

router = APIRouter(prefix="/services", tags=["registry"])


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_write_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.registry_session_factory
    async with session_factory() as session:
        yield session


@router.get("", response_model=ServicesOut)
async def list_services_endpoint(session: AsyncSession = Depends(get_read_session)) -> ServicesOut:
    return ServicesOut(items=await list_services(session))


@router.post("", response_model=ServiceCreateResponse, status_code=201)
async def create_service_endpoint(
    body: ServiceCreate, session: AsyncSession = Depends(get_write_session)
) -> ServiceCreateResponse:
    try:
        service, api_key = await create_service(session, body)
    except ServiceNameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnknownDependency as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ServiceCreateResponse(service=service, api_key=api_key)


@router.get("/{service_id}", response_model=ServiceOut)
async def get_service_endpoint(
    service_id: UUID, session: AsyncSession = Depends(get_read_session)
) -> ServiceOut:
    service = await get_service(session, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="service not found")
    return service


@router.patch("/{service_id}", response_model=ServiceOut)
async def patch_service_endpoint(
    service_id: UUID, body: ServicePatch, session: AsyncSession = Depends(get_write_session)
) -> ServiceOut:
    try:
        service = await patch_service(session, service_id, body)
    except UnknownDependency as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if service is None:
        raise HTTPException(status_code=404, detail="service not found")
    return service


@router.delete("/{service_id}", status_code=204)
async def delete_service_endpoint(
    service_id: UUID,
    purge: bool = Query(False),
    session: AsyncSession = Depends(get_write_session),
) -> Response:
    deleted = await delete_service(session, service_id, purge=purge)
    if not deleted:
        raise HTTPException(status_code=404, detail="service not found")
    return Response(status_code=204)


@router.post("/{service_id}/keys", response_model=KeyCreateResponse, status_code=201)
async def create_key_endpoint(
    service_id: UUID, body: KeyCreate, session: AsyncSession = Depends(get_write_session)
) -> KeyCreateResponse:
    result = await create_key(session, service_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="service not found")
    key, api_key = result
    return KeyCreateResponse(api_key=api_key, key_id=key.id, label=key.label)


@router.delete("/{service_id}/keys/{key_id}", status_code=204)
async def revoke_key_endpoint(
    service_id: UUID, key_id: UUID, session: AsyncSession = Depends(get_write_session)
) -> Response:
    revoked = await revoke_key(session, service_id, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="key not found")
    return Response(status_code=204)
