"""HTTP shapes for the two things `app/registry/` still owns: ingest API
keys and the Phase 19 topology-suggestion queue.

Everything that described a *service* — `ServiceOut`, `ServiceCreate`,
`ServicePatch` and the `depends_on` list — went with the `/services`
alias in Phase 30 (field 6). A component is described by
`app/model/schemas.py`'s `ComponentOut` now, which carries its keys as a
list of the `KeyOut` below. The endpoints these shapes belong to are
mounted under `/model` by `app/model/router.py`.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class KeyOut(BaseModel):
    """An ingest key's metadata. Never its hash and never its plaintext —
    see api/tests/test_model_api.py's string-search assertion, which
    exists specifically because a schema-only review would not catch a
    field like `key_hash` being added back in later."""

    id: UUID
    label: str | None
    #: Nullable because the column is: `api_keys.created_at` has a
    #: server default and no NOT NULL (`ApiKey.created_at` in
    #: app/db/models.py; .claude/rules/database.md, "Nullability is part
    #: of the schema"). The
    #: `/services` alias claimed `datetime` and papered over the
    #: difference with a type-ignore; the honest type costs the
    #: dashboard one null check.
    created_at: datetime | None
    last_used_at: datetime | None
    revoked: bool


class KeyCreate(BaseModel):
    label: str | None = None


class KeyCreateResponse(BaseModel):
    """`api_key` is returned exactly once, here — never retrievable again,
    not even by an admin. Losing it means issuing another."""

    api_key: str
    key_id: UUID
    label: str | None


class TopologySuggestionOut(BaseModel):
    """A machine-observed edge (Phase 19, Option A) not yet declared as a
    connection of any kind and not dismissed. `*_registered` lets the UI
    show which endpoint(s) would block acceptance — see
    app/registry/service.py's UnregisteredEndpoint.

    The field names still say `service` because `observed_service_edges`
    does: the ingest gateway records the OTel `service.name` on each side
    of a CLIENT span, which is a component name by another name."""

    from_service: str
    to_service: str
    observations: int
    first_seen_at: datetime
    last_seen_at: datetime
    from_service_registered: bool
    to_service_registered: bool


class TopologySuggestionsOut(BaseModel):
    items: list[TopologySuggestionOut]


class TopologyEdgeRef(BaseModel):
    from_service: str
    to_service: str
