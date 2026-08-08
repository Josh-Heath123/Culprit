import os

#: postmortem-writer role (Phase 18) — SELECT/INSERT/UPDATE/DELETE on
#: postmortems, SELECT on incident_candidates (to validate a postmortem's
#: optional incident_id at create time). GET /postmortems stays on the
#: existing api-reader engine (already has SELECT on postmortems — see
#: api/migrations/versions/cc323b6c7779_create_db_roles.py); only writes
#: use this one.
POSTMORTEM_WRITER_DATABASE_URL = os.environ.get(
    "POSTMORTEM_WRITER_DATABASE_URL",
    "postgresql+asyncpg://postmortem-writer:postmortem-writer-dev-password@localhost:5432/signalstack",
)
