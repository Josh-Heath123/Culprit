"""Demo fixture topology for the three toy services (Phase 2) — no
longer the product's source of truth for service topology.

Phase 14 replaced that role with a real `services` table
(api/app/db/models.py's Service/ServiceDependency, managed through
api/app/registry/): a service is a row created through the registry
API, and worker/app/correlation/job.py loads adjacency from the
database per run instead of importing a hardcoded dict. This module
still exists — and is still imported — for exactly one purpose:
demo-services/shared/otel.py needs to know which environment variable
holds each demo service's own API key, and that mapping only ever
described these three fixture services in the first place.

worker/app/correlation/graph.py must NOT import from here anymore (see
its own module docstring / Phase 14's Trap in
docs/SELF_HOSTED_PLAN.md) — adjacency is a parameter now, not an import.

api/migrations/versions/48c0b29fa215_create_api_keys_table.py keeps its
own literal copy of the env-var mapping rather than importing this
module — migrations are historical snapshots and shouldn't depend on
live/mutable application code; see that migration's own docstring.
frontend/src/lib/services.ts's old hand-synced mirror of the service
list is gone entirely (Phase 14): the frontend now fetches services from
GET /services (see frontend/src/hooks/useServices.ts).
"""

#: order-service calls both inventory-service and payments-service
#: directly; inventory-service and payments-service have no direct
#: relationship to each other (only via order-service). Fixture data
#: only — real adjacency for registered services lives in the
#: service_dependencies table now.
DEMO_SERVICE_ADJACENCY: dict[str, frozenset[str]] = {
    "order-service": frozenset({"inventory-service", "payments-service"}),
    "inventory-service": frozenset({"order-service"}),
    "payments-service": frozenset({"order-service"}),
}

DEMO_SERVICES: tuple[str, ...] = ("order-service", "inventory-service", "payments-service")

#: Which environment variable holds each demo service's ingest-gateway
#: API key. The one constant in this module still actually imported by
#: application code (demo-services/shared/otel.py) — everything else
#: here is fixture data kept for tests/local docs, not a live dependency.
DEMO_SERVICE_API_KEY_ENV_VARS: dict[str, str] = {
    "order-service": "ORDER_SERVICE_API_KEY",
    "inventory-service": "INVENTORY_SERVICE_API_KEY",
    "payments-service": "PAYMENTS_SERVICE_API_KEY",
}
