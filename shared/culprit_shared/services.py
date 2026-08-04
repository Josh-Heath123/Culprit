"""The Phase 2 demo topology — hardcoded per the project's own scope rule
(CLAUDE.md: "two to three services, hardcoded, not N services
configurable"), not general service-topology discovery.

Single source for the three places that used to hand-duplicate this:
worker/app/correlation/graph.py's SERVICE_ADJACENCY and
demo-services/shared/otel.py's API-key-env-var mapping now import these
directly. api/migrations/versions/48c0b29fa215_create_api_keys_table.py
deliberately still keeps its own literal copy of the env-var mapping —
migrations are historical snapshots and shouldn't import live/mutable
application code (a later change here shouldn't retroactively change
what an already-applied migration is understood to have done); if the
service list ever changes, that needs a new migration anyway, not an
edit to this one. frontend/src/lib/services.ts is the hand-synced TS
mirror of SERVICES below — see that file's comment.
"""

#: order-service calls both inventory-service and payments-service
#: directly; inventory-service and payments-service have no direct
#: relationship to each other (only via order-service).
SERVICE_ADJACENCY: dict[str, frozenset[str]] = {
    "order-service": frozenset({"inventory-service", "payments-service"}),
    "inventory-service": frozenset({"order-service"}),
    "payments-service": frozenset({"order-service"}),
}

#: Ordered — lane order on the frontend timeline matches this.
SERVICES: tuple[str, ...] = ("order-service", "inventory-service", "payments-service")

#: Which environment variable holds each service's ingest-gateway API key.
SERVICE_API_KEY_ENV_VARS: dict[str, str] = {
    "order-service": "ORDER_SERVICE_API_KEY",
    "inventory-service": "INVENTORY_SERVICE_API_KEY",
    "payments-service": "PAYMENTS_SERVICE_API_KEY",
}
