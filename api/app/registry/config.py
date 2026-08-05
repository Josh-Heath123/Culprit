import os

#: registry-admin role (Phase 14) — SELECT/INSERT/UPDATE/DELETE on
#: services, service_dependencies, api_keys only. Every other write path
#: in this API still goes through worker-side roles; this is the one
#: exception because service/key management genuinely is an admin HTTP
#: action, not a background job. GET /services may use the api-reader
#: engine already in app.state (see app/incidents/config.py) — only
#: writes need this one.
REGISTRY_ADMIN_DATABASE_URL = os.environ.get(
    "REGISTRY_ADMIN_DATABASE_URL",
    "postgresql+asyncpg://registry-admin:registry-admin-dev-password@localhost:5432/signalstack",
)
