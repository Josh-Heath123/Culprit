"""HTTP shapes for the system model (Phase 27, field 9).

Components and connections are addressed by **name** in every request
body, not by id. A `culprit.yaml` names components, the OTel resource
attribute names components, and an operator thinks in names; forcing a
caller to resolve `orders-svc` to a UUID before it can declare an edge
would make the API strictly harder to use than the file it mirrors.
Responses carry ids as well, because the frontend needs a stable key.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from culprit_model.graph import ComponentKind, ConnectionKind, Criticality, DeclaredBy
from pydantic import BaseModel, ConfigDict, Field

from app.registry.schemas import KeyOut

#: Same pattern as app/model/manifest.py's COMPONENT_NAME_PATTERN (and
#: the Phase 14 registry's SERVICE_NAME_PATTERN before it) — must match the OTel
#: `service.name` resource attribute byte-for-byte.
COMPONENT_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,62}$"


class ComponentOut(BaseModel):
    """Never include key_hash or any plaintext key material — see
    api/tests/test_model_api.py's string-search assertion, inherited from
    the Phase 14 registry test that exists specifically because a
    schema-only review would not catch a field like `keys[].key_hash`
    being added back in later."""

    id: UUID
    name: str
    display_name: str | None
    kind: ComponentKind
    sort_order: int
    monitored_metrics: list[str]
    environment_scope: list[str]
    labels: dict[str, Any]
    disabled: bool
    #: The component's ingest keys — metadata only, revoked ones
    #: included (see KeyOut). Phase 30 moved this here from the removed
    #: `/services` alias's `ServiceOut`, which was the only shape that
    #: carried it; without it Settings → Services had no way to list or
    #: revoke a key once the alias was gone.
    keys: list[KeyOut] = Field(default_factory=list)
    created_at: datetime | None


class ComponentsOut(BaseModel):
    items: list[ComponentOut]


class ComponentCreate(BaseModel):
    name: str = Field(pattern=COMPONENT_NAME_PATTERN)
    display_name: str | None = None
    kind: ComponentKind = ComponentKind.SERVICE
    monitored_metrics: list[str] = Field(default_factory=list)
    environment_scope: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)
    #: Display order, and the mechanism that makes a `culprit.yaml`
    #: round trip preserve the author's component ordering —
    #: `apply_manifest` passes each component's position in the file.
    sort_order: int = 0


class ComponentCreateResponse(BaseModel):
    """`api_key` is returned exactly once, here — never retrievable again
    (only a new key can be issued, via POST /model/components/{id}/keys)."""

    component: ComponentOut
    api_key: str


class ComponentPatch(BaseModel):
    """All fields optional; only the ones actually present in the request
    body are applied (`exclude_unset=True` in app/model/service.py) — a
    PATCH that omits `display_name` must leave it alone, not null it."""

    display_name: str | None = None
    kind: ComponentKind | None = None
    sort_order: int | None = None
    monitored_metrics: list[str] | None = None
    environment_scope: list[str] | None = None
    labels: dict[str, Any] | None = None
    disabled: bool | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    from_component: str
    to_component: str
    kind: ConnectionKind
    #: Null throughout Phase 27 — that phase's field 17 says connections
    #: may carry a null contract, and Phase 28's extractors populate it.
    contract_id: UUID | None
    declared_by: DeclaredBy
    criticality: Criticality
    created_at: datetime


class ConnectionsOut(BaseModel):
    items: list[ConnectionOut]


class ConnectionCreate(BaseModel):
    from_component: str
    to_component: str
    kind: ConnectionKind = ConnectionKind.HTTP
    criticality: Criticality = Criticality.UNKNOWN
    declared_by: DeclaredBy = DeclaredBy.CULPRIT_YAML


class ConnectionPatch(BaseModel):
    kind: ConnectionKind | None = None
    criticality: Criticality | None = None
    declared_by: DeclaredBy | None = None


class GraphOut(BaseModel):
    """`GET /model/graph`.

    `request_path` is populated only when the caller named a `symptom`,
    and is the phase's fourth acceptance criterion: the ordered set of
    upstream connections on that component's request path, nearest hop
    first. It is a field on the graph response rather than its own
    endpoint because it is a *view of* the graph, and computing it needs
    the whole graph loaded anyway.
    """

    components: list[ComponentOut]
    connections: list[ConnectionOut]
    symptom: str | None = None
    request_path: list[ConnectionOut] = Field(default_factory=list)


class ApplyResult(BaseModel):
    """What `POST /model/apply` changed.

    Counts, plus the names, because "3 connections removed" without
    saying which is not something an operator can review after the fact.
    """

    components_created: list[str] = Field(default_factory=list)
    components_updated: list[str] = Field(default_factory=list)
    components_disabled: list[str] = Field(default_factory=list)
    connections_created: list[str] = Field(default_factory=list)
    connections_updated: list[str] = Field(default_factory=list)
    connections_removed: list[str] = Field(default_factory=list)
    #: Keys issued for components this apply created, by component name.
    #: Same rule as ComponentCreateResponse: returned once, never again.
    api_keys: dict[str, str] = Field(default_factory=dict)


class ApplyRequest(BaseModel):
    """The manifest as text, not as a parsed structure.

    Deliberately: `app/model/manifest.py` is the one thing that decides
    what a `culprit.yaml` means, including the credential refusal in
    field 12. Accepting pre-parsed JSON here would route around it.
    """

    manifest: str
    #: Mirrors `apply_model.py --prune`. Off by default: a manifest that
    #: happens to omit a component should not silently disable it.
    prune: bool = False


class ExportOut(BaseModel):
    manifest: str
