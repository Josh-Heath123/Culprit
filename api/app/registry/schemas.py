from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

#: Must match the OTel `service.name` resource attribute byte-for-byte
#: (see docs/SELF_HOSTED_PLAN.md Phase 14) — reject anything that would
#: produce a confusing mismatch (uppercase, spaces, leading punctuation).
SERVICE_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,62}$"


class KeyOut(BaseModel):
    id: UUID
    label: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class ServiceOut(BaseModel):
    """Never include key_hash or any plaintext key material — see
    api/tests/test_registry_api.py's string-search assertion, which
    exists specifically because a schema-only review wouldn't catch a
    field like `keys[].key_hash` being added back in later."""

    id: UUID
    name: str
    display_name: str | None
    sort_order: int
    monitored_metrics: list[str]
    disabled: bool
    depends_on: list[str]
    keys: list[KeyOut]
    created_at: datetime | None


class ServicesOut(BaseModel):
    items: list[ServiceOut]


class ServiceCreate(BaseModel):
    name: str = Field(pattern=SERVICE_NAME_PATTERN)
    display_name: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    monitored_metrics: list[str] = Field(default_factory=list)


class ServiceCreateResponse(BaseModel):
    """`api_key` is returned exactly once, here — never retrievable again
    (not even by an admin; only a new key can be issued via
    POST /services/{id}/keys)."""

    service: ServiceOut
    api_key: str


class ServicePatch(BaseModel):
    """All fields optional; only the ones actually present in the request
    body are applied (see api/app/registry/service.py's use of
    `exclude_unset=True`) — a PATCH that omits `display_name` must leave
    it alone, not null it out."""

    display_name: str | None = None
    sort_order: int | None = None
    monitored_metrics: list[str] | None = None
    depends_on: list[str] | None = None
    disabled: bool | None = None


class KeyCreate(BaseModel):
    label: str | None = None


class KeyCreateResponse(BaseModel):
    api_key: str
    key_id: UUID
    label: str | None
