"""System model admin API (Phase 27, field 9) — mounted at `/model` in
api/app/main.py behind `require_admin`, the same gate the registry
router has had since Phase 16.

Reads use the `api-reader` engine already in `app.state`; writes use the
`registry-admin` engine — see `app/main.py`'s lifespan. The two session
dependencies are deliberately identical to `app/registry/router.py`'s
rather than shared with it, because that module is now a compatibility
shim on its way out (field 9: retained for one release, removed in Phase
30) and importing from it would make the shim load-bearing.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from culprit_model.graph import UnknownComponent
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from app.model.manifest import ManifestError, dump_manifest, load_manifest
from app.model.schemas import (
    ApplyRequest,
    ApplyResult,
    ComponentCreate,
    ComponentCreateResponse,
    ComponentOut,
    ComponentPatch,
    ComponentsOut,
    ConnectionCreate,
    ConnectionOut,
    ConnectionPatch,
    ConnectionsOut,
    ExportOut,
    GraphOut,
)
from app.model.service import (
    ComponentNameTaken,
    DuplicateConnection,
    SelfConnection,
    UnknownComponentName,
    apply_manifest,
    create_component,
    create_connection,
    delete_component,
    delete_connection,
    export_manifest,
    get_component,
    list_components,
    list_connections,
    patch_component,
    patch_connection,
    request_path,
)

router = APIRouter(prefix="/model", tags=["model"])


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_write_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.registry_session_factory
    async with session_factory() as session:
        yield session


# --- components -------------------------------------------------------


@router.get("/components", response_model=ComponentsOut)
async def list_components_endpoint(
    session: AsyncSession = Depends(get_read_session),
) -> ComponentsOut:
    return ComponentsOut(items=await list_components(session))


@router.post("/components", response_model=ComponentCreateResponse, status_code=201)
async def create_component_endpoint(
    body: ComponentCreate, session: AsyncSession = Depends(get_write_session)
) -> ComponentCreateResponse:
    try:
        component, api_key = await create_component(session, body)
    except ComponentNameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ComponentCreateResponse(component=component, api_key=api_key)


@router.get("/components/{component_id}", response_model=ComponentOut)
async def get_component_endpoint(
    component_id: UUID, session: AsyncSession = Depends(get_read_session)
) -> ComponentOut:
    component = await get_component(session, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="component not found")
    return component


@router.patch("/components/{component_id}", response_model=ComponentOut)
async def patch_component_endpoint(
    component_id: UUID,
    body: ComponentPatch,
    session: AsyncSession = Depends(get_write_session),
) -> ComponentOut:
    component = await patch_component(session, component_id, body)
    if component is None:
        raise HTTPException(status_code=404, detail="component not found")
    return component


@router.delete("/components/{component_id}", status_code=204)
async def delete_component_endpoint(
    component_id: UUID,
    purge: bool = Query(False),
    session: AsyncSession = Depends(get_write_session),
) -> Response:
    if not await delete_component(session, component_id, purge=purge):
        raise HTTPException(status_code=404, detail="component not found")
    return Response(status_code=204)


# --- connections ------------------------------------------------------


@router.get("/connections", response_model=ConnectionsOut)
async def list_connections_endpoint(
    session: AsyncSession = Depends(get_read_session),
) -> ConnectionsOut:
    return ConnectionsOut(items=await list_connections(session))


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def create_connection_endpoint(
    body: ConnectionCreate, session: AsyncSession = Depends(get_write_session)
) -> ConnectionOut:
    try:
        return await create_connection(session, body)
    except UnknownComponentName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SelfConnection as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateConnection as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def patch_connection_endpoint(
    connection_id: UUID,
    body: ConnectionPatch,
    session: AsyncSession = Depends(get_write_session),
) -> ConnectionOut:
    connection = await patch_connection(session, connection_id, body)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    return connection


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection_endpoint(
    connection_id: UUID, session: AsyncSession = Depends(get_write_session)
) -> Response:
    if not await delete_connection(session, connection_id):
        raise HTTPException(status_code=404, detail="connection not found")
    return Response(status_code=204)


# --- the graph --------------------------------------------------------


@router.get("/graph", response_model=GraphOut)
async def get_graph_endpoint(
    symptom: str | None = Query(
        None,
        description=(
            "A component name. When given, `request_path` is the ordered set of "
            "upstream connections on that component's request path, nearest hop "
            "first. Background connections are excluded; unclassified ones are not."
        ),
    ),
    session: AsyncSession = Depends(get_read_session),
) -> GraphOut:
    # Disabled components are excluded from the graph, not just from the
    # request path. `load_graph` already drops them, so returning them in
    # `components` would hand a caller nodes that every path computation
    # treats as absent — a graph that draws a node no traversal can
    # reach. GET /model/components still lists them, which is what
    # Settings needs to offer an "Enable" button.
    components = [
        component for component in await list_components(session) if not component.disabled
    ]
    live = {component.name for component in components}
    connections = [
        connection
        for connection in await list_connections(session)
        if connection.from_component in live and connection.to_component in live
    ]
    if symptom is None:
        return GraphOut(components=components, connections=connections)

    try:
        path = await request_path(session, symptom)
    except UnknownComponent as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GraphOut(
        components=components,
        connections=connections,
        symptom=symptom,
        request_path=path,
    )


# --- culprit.yaml -----------------------------------------------------


@router.post("/apply", response_model=ApplyResult)
async def apply_endpoint(
    body: ApplyRequest, session: AsyncSession = Depends(get_write_session)
) -> ApplyResult:
    try:
        manifest = load_manifest(body.manifest)
    except ManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await apply_manifest(session, manifest, prune=body.prune)
    except UnknownComponentName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export", response_model=ExportOut)
async def export_endpoint(session: AsyncSession = Depends(get_read_session)) -> ExportOut:
    """The model as a `culprit.yaml`.

    Not in field 9's list, and present because acceptance criterion 2
    ("apply, export, diff is empty") is untestable without it and
    `apply_model.py --export` needs the same code path. It is a read of
    the model, not a new capability.
    """
    return ExportOut(manifest=dump_manifest(await export_manifest(session)))
