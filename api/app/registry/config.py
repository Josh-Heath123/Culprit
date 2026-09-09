from app.env import require_env

#: registry-admin role (Phase 14) — SELECT/INSERT/UPDATE/DELETE on
#: services, service_dependencies, api_keys only. Every other write path
#: in this API still goes through worker-side roles; this is the one
#: exception because service/key management genuinely is an admin HTTP
#: action, not a background job. GET /services may use the api-reader
#: engine already in app.state (see app/incidents/config.py) — only
#: writes need this one.
#: No dev-password fallback -- see app/env.py and Phase 26.
REGISTRY_ADMIN_DATABASE_URL = require_env(
    "REGISTRY_ADMIN_DATABASE_URL", hint="see infra/.env.prod.example"
)
