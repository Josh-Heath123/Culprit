"""The demo services' API-key environment variables. Nothing else.

Phase 27 removed this module's last piece of topology fixture data
(DEMO_SERVICE_ADJACENCY, and the DEMO_SERVICES tuple beside it): the demo
system is described by demo-services/culprit.yaml now, applied with
`just apply-model`, so a second hardcoded copy of the same three-service
graph in Python had nothing left to be right about.

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
list is gone entirely (Phase 14): the frontend fetches the registered
list from the API — GET /model/components since Phase 30 removed the
/services alias (see frontend/src/hooks/useModel.ts).
"""

#: Which environment variable holds each demo service's ingest-gateway
#: API key — the only constant left here, and the reason this module
#: still exists: demo-services/shared/otel.py imports it. A culprit.yaml
#: names components, never secrets (Phase 27 field 12), so this mapping
#: has nowhere to move to.
DEMO_SERVICE_API_KEY_ENV_VARS: dict[str, str] = {
    "order-service": "ORDER_SERVICE_API_KEY",
    "inventory-service": "INVENTORY_SERVICE_API_KEY",
    "payments-service": "PAYMENTS_SERVICE_API_KEY",
}
