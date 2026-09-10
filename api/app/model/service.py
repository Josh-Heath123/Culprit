"""DB access for the system model (Phase 27).

Structured the way `app/registry/service.py` was: the `registry-admin`
role for writes, whatever engine the caller passes for reads (see
`app/main.py`'s lifespan). Transform logic (ORM row -> `ComponentOut`)
lives here rather than a separate `transforms.py`, matching the package
it grew out of.

**Why the write role did not change.** `registry-admin` already held
SELECT/INSERT/UPDATE/DELETE on `services`, `service_dependencies` and
`api_keys`. Phase 27 renamed the first to `components` (the grant
followed the table) and replaced the second with `connections` (the
migration re-granted exactly the same verbs). No role gained a table it
could not previously write, or a verb it did not previously have, so
`.claude/rules/database.md`'s "add a role, never widen one" is satisfied
without a new role — the same reasoning Phase 19 used.

`contracts` is untouched here: no grant, no reads, no writes, per Phase
27's field 17.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from culprit_model.canonical import canonical_component
from culprit_model.graph import (
    Component as GraphComponent,
)
from culprit_model.graph import (
    ComponentKind,
    ConnectionKind,
    Criticality,
    DeclaredBy,
    SystemGraph,
    UnknownComponent,
)
from culprit_model.graph import (
    Connection as GraphConnection,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ApiKey, Component, Connection
from app.model.manifest import ComponentSpec, ConnectionSpec, Manifest
from app.model.schemas import (
    ApplyResult,
    ComponentCreate,
    ComponentOut,
    ComponentPatch,
    ConnectionCreate,
    ConnectionOut,
    ConnectionPatch,
)
from app.registry.keys import generate_api_key, hash_api_key
from app.registry.schemas import KeyOut


class ComponentNameTaken(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"a component named {name!r} already exists")


class UnknownComponentName(Exception):
    """A request named a component that is not in the model.

    Reported rather than skipped — the pre-Phase-27 registry made the
    same choice for `depends_on`, and for the same reason: a live admin
    call naming a component that does not exist is a mistake to surface,
    not a row to drop.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"unknown component name(s): {', '.join(sorted(names))}")


class DuplicateConnection(Exception):
    def __init__(self, source: str, target: str, kind: str) -> None:
        super().__init__(f"a {kind} connection {source!r} -> {target!r} already exists")


class SelfConnection(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"a connection cannot loop back on {name!r}")


# --- transforms -------------------------------------------------------


def _key_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        label=key.label,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked=key.revoked_at is not None,
    )


def component_out(component: Component) -> ComponentOut:
    """Requires `api_keys` to be loaded already (`selectinload`), as every
    query in this module that feeds it does. An async session cannot
    lazy-load, so a caller that forgets fails loudly with
    `MissingGreenlet` rather than returning a component with no keys."""
    return ComponentOut(
        id=component.id,
        name=component.name,
        display_name=component.display_name,
        kind=ComponentKind(component.kind),
        sort_order=component.sort_order,
        monitored_metrics=component.monitored_metrics,
        environment_scope=component.environment_scope,
        labels=component.labels,
        disabled=component.disabled_at is not None,
        keys=[_key_out(key) for key in component.api_keys],
        created_at=component.created_at,
    )


def _connection_out(connection: Connection, name_by_id: dict[UUID, str]) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        from_component=name_by_id[connection.from_component_id],
        to_component=name_by_id[connection.to_component_id],
        kind=ConnectionKind(connection.kind),
        contract_id=connection.contract_id,
        declared_by=DeclaredBy(connection.declared_by),
        criticality=Criticality(connection.criticality),
        created_at=connection.created_at,
    )


# --- lookups ----------------------------------------------------------


async def _name_by_id(session: AsyncSession) -> dict[UUID, str]:
    rows = (await session.execute(select(Component.id, Component.name))).all()
    return {row_id: name for row_id, name in rows}


async def _resolve_names(session: AsyncSession, names: list[str]) -> dict[str, UUID]:
    """Maps component names to ids, raising for any that do not exist."""
    if not names:
        return {}
    canonical = [canonical_component(name) for name in names]
    rows = (
        await session.execute(
            select(Component.id, Component.name).where(Component.name.in_(canonical))
        )
    ).all()
    id_by_name = {name: row_id for row_id, name in rows}
    missing = [name for name in canonical if name not in id_by_name]
    if missing:
        raise UnknownComponentName(missing)
    return id_by_name


async def _get_component_orm(session: AsyncSession, component_id: UUID) -> Component | None:
    return (
        await session.execute(
            select(Component)
            .options(selectinload(Component.api_keys))
            .where(Component.id == component_id)
        )
    ).scalar_one_or_none()


async def list_components(session: AsyncSession) -> list[ComponentOut]:
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
    return [component_out(c) for c in components]


async def get_component(session: AsyncSession, component_id: UUID) -> ComponentOut | None:
    component = await _get_component_orm(session, component_id)
    return None if component is None else component_out(component)


async def list_connections(session: AsyncSession) -> list[ConnectionOut]:
    name_by_id = await _name_by_id(session)
    connections = (await session.execute(select(Connection))).scalars().all()
    return sorted(
        (_connection_out(c, name_by_id) for c in connections),
        key=lambda c: (c.from_component, c.to_component, str(c.kind)),
    )


# --- component writes -------------------------------------------------


async def create_component(
    session: AsyncSession, data: ComponentCreate
) -> tuple[ComponentOut, str]:
    """Creates a component and issues its first ingest API key.

    Every component gets a key, including a `database` or `external_api`
    one that will never present it. That is deliberate continuity with
    the Phase 14 registry rather than a new decision: a key costs a row,
    and making key issuance conditional on `kind` would mean a component
    whose kind was corrected later silently had no way to ingest.
    """
    name = canonical_component(data.name)
    existing = (
        await session.execute(select(Component.id).where(Component.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        raise ComponentNameTaken(name)

    component = Component(
        name=name,
        display_name=data.display_name,
        kind=str(data.kind),
        monitored_metrics=data.monitored_metrics,
        environment_scope=data.environment_scope,
        labels=data.labels,
        sort_order=data.sort_order,
    )
    session.add(component)
    await session.flush()

    plaintext = generate_api_key()
    session.add(
        ApiKey(
            service_name=component.name,
            service_id=component.id,
            key_hash=hash_api_key(plaintext),
            label="initial",
        )
    )
    await session.commit()

    out = await get_component(session, component.id)
    assert out is not None
    return out, plaintext


async def patch_component(
    session: AsyncSession, component_id: UUID, patch: ComponentPatch
) -> ComponentOut | None:
    component = await _get_component_orm(session, component_id)
    if component is None:
        return None

    fields = patch.model_dump(exclude_unset=True)
    if "display_name" in fields:
        component.display_name = fields["display_name"]
    if "kind" in fields:
        component.kind = str(fields["kind"])
    if "sort_order" in fields:
        component.sort_order = fields["sort_order"]
    if "monitored_metrics" in fields:
        component.monitored_metrics = fields["monitored_metrics"]
    if "environment_scope" in fields:
        component.environment_scope = fields["environment_scope"]
    if "labels" in fields:
        component.labels = fields["labels"]
    if "disabled" in fields:
        component.disabled_at = datetime.now(UTC) if fields["disabled"] else None

    await session.commit()
    return await get_component(session, component_id)


async def delete_component(session: AsyncSession, component_id: UUID, *, purge: bool) -> bool:
    """Soft delete (default) sets `disabled_at` only — every historical
    raw_events/anomalies/incident_candidates row survives, and so does the
    component row. `purge=True` hard-deletes it and, via the FKs' own
    ON DELETE CASCADE, its api_keys and connections, but still never
    touches telemetry tables (raw_events has no FK to components at all,
    on purpose — see api/app/db/models.py's RawEvent docstring).
    """
    if purge:
        # A Core DELETE, not session.delete(component) on the loaded ORM
        # object: the ORM's unit-of-work nulls a loaded collection's FK
        # before deleting the parent, and api_keys.service_id is NOT
        # NULL, so that null-out fails outright. A Core statement skips
        # relationship handling and lets ON DELETE CASCADE do the work.
        existing = (
            await session.execute(select(Component.id).where(Component.id == component_id))
        ).scalar_one_or_none()
        if existing is None:
            return False
        await session.execute(delete(Component).where(Component.id == component_id))
        await session.commit()
        return True

    component = await _get_component_orm(session, component_id)
    if component is None:
        return False
    component.disabled_at = datetime.now(UTC)
    await session.commit()
    return True


# --- connection writes ------------------------------------------------


async def create_connection(session: AsyncSession, data: ConnectionCreate) -> ConnectionOut:
    source = canonical_component(data.from_component)
    target = canonical_component(data.to_component)
    if source == target:
        raise SelfConnection(source)

    id_by_name = await _resolve_names(session, [source, target])
    existing = (
        await session.execute(
            select(Connection.id).where(
                Connection.from_component_id == id_by_name[source],
                Connection.to_component_id == id_by_name[target],
                Connection.kind == str(data.kind),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateConnection(source, target, str(data.kind))

    connection = Connection(
        from_component_id=id_by_name[source],
        to_component_id=id_by_name[target],
        kind=str(data.kind),
        declared_by=str(data.declared_by),
        criticality=str(data.criticality),
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return _connection_out(connection, await _name_by_id(session))


async def patch_connection(
    session: AsyncSession, connection_id: UUID, patch: ConnectionPatch
) -> ConnectionOut | None:
    connection = (
        await session.execute(select(Connection).where(Connection.id == connection_id))
    ).scalar_one_or_none()
    if connection is None:
        return None

    fields = patch.model_dump(exclude_unset=True)
    if "kind" in fields:
        connection.kind = str(fields["kind"])
    if "criticality" in fields:
        connection.criticality = str(fields["criticality"])
    if "declared_by" in fields:
        connection.declared_by = str(fields["declared_by"])

    await session.commit()
    await session.refresh(connection)
    return _connection_out(connection, await _name_by_id(session))


async def delete_connection(session: AsyncSession, connection_id: UUID) -> bool:
    """Always a hard delete, unlike a component's default soft delete.

    A connection carries no history of its own — no telemetry row points
    at one — so there is nothing a `disabled_at` would preserve, and a
    tombstoned edge that still appeared in the graph would be worse than
    no edge.
    """
    existing = (
        await session.execute(select(Connection.id).where(Connection.id == connection_id))
    ).scalar_one_or_none()
    if existing is None:
        return False
    await session.execute(delete(Connection).where(Connection.id == connection_id))
    await session.commit()
    return True


# --- the graph --------------------------------------------------------


async def load_graph(session: AsyncSession, *, include_disabled: bool = False) -> SystemGraph:
    """Builds the in-memory `SystemGraph` from the two tables.

    Disabled components are excluded by default, and so is any connection
    touching one — a disabled component is one whose telemetry the
    pipeline has stopped reading, so leaving it on a request path would
    put a node in every report that nothing can say anything about.
    """
    query = select(Component)
    if not include_disabled:
        query = query.where(Component.disabled_at.is_(None))
    components = (await session.execute(query)).scalars().all()
    keep = {component.id for component in components}

    connections = (await session.execute(select(Connection))).scalars().all()
    name_by_id = {component.id: component.name for component in components}

    return SystemGraph(
        components=tuple(
            GraphComponent(
                name=component.name,
                kind=ComponentKind(component.kind),
                environment_scope=tuple(component.environment_scope),
                labels=component.labels,
            )
            for component in components
        ),
        connections=tuple(
            GraphConnection(
                from_component=name_by_id[connection.from_component_id],
                to_component=name_by_id[connection.to_component_id],
                kind=ConnectionKind(connection.kind),
                contract_id=str(connection.contract_id) if connection.contract_id else None,
                declared_by=DeclaredBy(connection.declared_by),
                criticality=Criticality(connection.criticality),
            )
            for connection in connections
            if connection.from_component_id in keep and connection.to_component_id in keep
        ),
    )


async def request_path(session: AsyncSession, symptom: str) -> list[ConnectionOut]:
    """Phase 27's fourth acceptance criterion, over real rows.

    Returns the same `ConnectionOut` shape `list_connections` does, in
    the order `SystemGraph.upstream_connections` produced, so a caller
    can render one list without a second lookup.
    """
    graph = await load_graph(session)
    ordered = graph.upstream_connections(symptom)

    by_key = {
        (c.from_component, c.to_component, str(c.kind)): c for c in await list_connections(session)
    }
    return [
        by_key[key]
        for key in (
            (edge.from_component, edge.to_component, str(edge.kind)) for edge in ordered
        )
        if key in by_key
    ]


# --- culprit.yaml apply / export --------------------------------------


async def export_manifest(session: AsyncSession) -> Manifest:
    """The DB as a `culprit.yaml`.

    Disabled components are omitted: the manifest describes the system as
    it is meant to be, and a disabled component is one an operator has
    said is not part of it. Re-applying an exported file therefore does
    not resurrect them, which is what makes the round trip in acceptance
    criterion 2 stable rather than oscillating.
    """
    components = (
        (
            await session.execute(
                select(Component)
                .where(Component.disabled_at.is_(None))
                # sort_order, then name: `apply_manifest` records each
                # component's position in the file as its sort_order, so
                # exporting in this order gives back the author's own
                # ordering rather than an alphabetised rearrangement of
                # it. That is what makes "apply, export, diff is empty"
                # (acceptance criterion 2) true of the *text*, not merely
                # of the set of components.
                .order_by(Component.sort_order, Component.name)
            )
        )
        .scalars()
        .all()
    )
    name_by_id = {component.id: component.name for component in components}
    connections = (await session.execute(select(Connection))).scalars().all()

    outgoing: dict[str, list[ConnectionSpec]] = defaultdict(list)
    for connection in connections:
        source = name_by_id.get(connection.from_component_id)
        target = name_by_id.get(connection.to_component_id)
        if source is None or target is None:
            continue
        # Only manifest-owned edges are exported. An accepted topology
        # suggestion or an inferred edge is not something the manifest
        # declared, and writing it into the file would silently transfer
        # ownership: `_apply_connections` treats every edge in the file
        # as `culprit_yaml`, so the next apply that dropped the line
        # would delete an edge a human had explicitly accepted — exactly
        # what `accept_topology_suggestion` promises will not happen.
        # They remain visible in GET /model/connections and in the UI.
        if connection.declared_by != str(DeclaredBy.CULPRIT_YAML):
            continue
        outgoing[source].append(
            ConnectionSpec(
                to=target,
                kind=ConnectionKind(connection.kind),
                criticality=Criticality(connection.criticality),
            )
        )

    return Manifest(
        components=tuple(
            ComponentSpec(
                name=component.name,
                kind=ComponentKind(component.kind),
                display_name=component.display_name,
                environments=tuple(component.environment_scope),
                labels=component.labels,
                monitored_metrics=tuple(component.monitored_metrics),
                connections=tuple(
                    sorted(outgoing[component.name], key=lambda c: (c.to, str(c.kind)))
                ),
            )
            for component in components
        )
    )


async def apply_manifest(
    session: AsyncSession, manifest: Manifest, *, prune: bool = False
) -> ApplyResult:
    """Makes the database match the manifest.

    Two passes over components before any connection is touched, for the
    same reason `apply_services.py` had them: a file declaring two new
    components that reference each other would otherwise fail on the
    first edge, and requiring the file to be topologically sorted is a
    demand on the author that the loader can simply absorb.

    Idempotent — re-applying an unchanged manifest performs no writes and
    returns an empty result. That is what makes the apply/export/diff
    round trip meaningful rather than merely convergent.
    """
    result = ApplyResult()

    existing = {
        component.name: component
        for component in (await session.execute(select(Component))).scalars().all()
    }

    # Pass 1: create missing components (no connections yet).
    for position, spec in enumerate(manifest.components):
        if spec.name in existing:
            continue
        _, api_key = await create_component(
            session,
            ComponentCreate(
                name=spec.name,
                display_name=spec.display_name,
                kind=spec.kind,
                monitored_metrics=list(spec.monitored_metrics),
                environment_scope=list(spec.environments),
                labels=spec.labels,
                # Set here, not left to pass 2: without it a first apply
                # reports every new component as created *and* updated,
                # which makes the report unreadable precisely when it
                # matters most.
                sort_order=position,
            ),
        )
        result.components_created.append(spec.name)
        result.api_keys[spec.name] = api_key

    existing = {
        component.name: component
        for component in (await session.execute(select(Component))).scalars().all()
    }

    # Pass 2: reconcile every component, including the ones just
    # created — a newly created component still needs its sort_order set
    # from its position in the file.
    for position, spec in enumerate(manifest.components):
        component = existing[spec.name]
        patch = _component_diff(component, spec, position)
        if patch is None:
            continue
        await patch_component(session, component.id, patch)
        result.components_updated.append(spec.name)

    # Pass 3: connections, now that every endpoint is guaranteed present.
    await _apply_connections(session, manifest, existing, result)

    if prune:
        declared = {spec.name for spec in manifest.components}
        for name, component in existing.items():
            if name not in declared and component.disabled_at is None:
                await delete_component(session, component.id, purge=False)
                result.components_disabled.append(name)

    return result


def _component_diff(
    component: Component, spec: ComponentSpec, position: int
) -> ComponentPatch | None:
    """Only the fields that actually differ.

    `ComponentPatch`'s `exclude_unset=True` means an omitted field is
    left alone, so including an unchanged one would be harmless but is
    needless churn on every apply — and churn is what makes an "apply
    made no changes" report untrustworthy.

    `position` is the component's index in the manifest, stored as
    `sort_order`. The manifest is the declarative source, so the order
    the author wrote is the order the model has — and it is what lets
    `export_manifest` hand the file back in the shape it arrived.
    """
    fields: dict = {}
    if position != component.sort_order:
        fields["sort_order"] = position
    if spec.display_name != component.display_name:
        fields["display_name"] = spec.display_name
    if str(spec.kind) != component.kind:
        fields["kind"] = spec.kind
    if sorted(spec.monitored_metrics) != sorted(component.monitored_metrics):
        fields["monitored_metrics"] = list(spec.monitored_metrics)
    if sorted(spec.environments) != sorted(component.environment_scope):
        fields["environment_scope"] = list(spec.environments)
    if spec.labels != component.labels:
        fields["labels"] = spec.labels
    # A component named in the manifest is part of the system, so
    # re-declaring a previously disabled one re-enables it. The opposite
    # (leaving it disabled while the file says it exists) would make the
    # file and the model disagree with no way to tell from the file.
    if component.disabled_at is not None:
        fields["disabled"] = False
    return ComponentPatch(**fields) if fields else None


async def _apply_connections(
    session: AsyncSession,
    manifest: Manifest,
    existing: dict[str, Component],
    result: ApplyResult,
) -> None:
    """Reconciles `connections` against the manifest.

    Connections declared in the manifest are authoritative: an edge in
    the database with `declared_by = culprit_yaml` that the file no
    longer lists is removed, because the file is the declarative source
    and a stale edge there is a lie about the topology. Edges that came
    from anywhere else — an accepted Phase 19 suggestion, or inference —
    are **left alone**, because the manifest never claimed to describe
    them and deleting them would make `apply` quietly destructive.
    """
    id_by_name = {name: component.id for name, component in existing.items()}
    desired: dict[tuple[UUID, UUID, str], ConnectionSpec] = {}
    for spec in manifest.components:
        for connection in spec.connections:
            desired[
                (id_by_name[spec.name], id_by_name[connection.to], str(connection.kind))
            ] = connection

    name_by_id = {component_id: name for name, component_id in id_by_name.items()}
    current = (await session.execute(select(Connection))).scalars().all()
    current_by_key = {
        (c.from_component_id, c.to_component_id, c.kind): c for c in current
    }

    def label(key: tuple[UUID, UUID, str]) -> str:
        return f"{name_by_id[key[0]]} -{key[2]}-> {name_by_id[key[1]]}"

    for key, spec in desired.items():
        connection = current_by_key.get(key)
        if connection is None:
            session.add(
                Connection(
                    from_component_id=key[0],
                    to_component_id=key[1],
                    kind=key[2],
                    declared_by=str(DeclaredBy.CULPRIT_YAML),
                    criticality=str(spec.criticality),
                )
            )
            result.connections_created.append(label(key))
        elif (
            connection.criticality != str(spec.criticality)
            or connection.declared_by != str(DeclaredBy.CULPRIT_YAML)
        ):
            connection.criticality = str(spec.criticality)
            connection.declared_by = str(DeclaredBy.CULPRIT_YAML)
            result.connections_updated.append(label(key))

    for key, connection in current_by_key.items():
        if key in desired:
            continue
        if connection.declared_by != str(DeclaredBy.CULPRIT_YAML):
            continue
        if key[0] not in name_by_id or key[1] not in name_by_id:
            continue
        await session.delete(connection)
        result.connections_removed.append(label(key))

    await session.commit()


__all__ = [
    "ComponentNameTaken",
    "DuplicateConnection",
    "SelfConnection",
    "UnknownComponent",
    "UnknownComponentName",
    "apply_manifest",
    "component_out",
    "create_component",
    "create_connection",
    "delete_component",
    "delete_connection",
    "export_manifest",
    "get_component",
    "list_components",
    "list_connections",
    "load_graph",
    "patch_component",
    "patch_connection",
    "request_path",
]
