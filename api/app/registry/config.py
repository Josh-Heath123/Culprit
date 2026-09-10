from app.env import require_env

#: registry-admin role (Phase 14) — SELECT/INSERT/UPDATE/DELETE on
#: components, connections, api_keys only (the first two were `services`
#: and `service_dependencies` until Phase 27; the grants followed the
#: rename), plus SELECT/UPDATE on observed_service_edges for dismissing
#: a topology suggestion (Phase 19). Every other write path in this API still goes through
#: worker-side roles; this is the one exception because component and
#: key management genuinely is an admin HTTP action, not a background
#: job. Every GET /model/* uses the api-reader engine already in
#: app.state (see app/incidents/config.py) — only writes need this one.
#: No dev-password fallback -- see app/env.py and Phase 26.
REGISTRY_ADMIN_DATABASE_URL = require_env(
    "REGISTRY_ADMIN_DATABASE_URL", hint="see infra/.env.prod.example"
)
