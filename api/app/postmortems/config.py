from app.env import require_env

#: postmortem-writer role (Phase 18) — SELECT/INSERT/UPDATE/DELETE on
#: postmortems, SELECT on incident_candidates (to validate a postmortem's
#: optional incident_id at create time). GET /postmortems stays on the
#: existing api-reader engine (already has SELECT on postmortems — see
#: api/migrations/versions/cc323b6c7779_create_db_roles.py); only writes
#: use this one.
#: No dev-password fallback -- see app/env.py and Phase 26.
POSTMORTEM_WRITER_DATABASE_URL = require_env(
    "POSTMORTEM_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
