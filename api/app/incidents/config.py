import os

from app.env import require_env

#: api-reader role (Phase 1) — SELECT only on raw_events/anomalies/
#: incident_candidates/incident_anomalies/postmortems. Nothing in this
#: package ever writes to Postgres directly; the one write this phase
#: triggers (a new root-cause narrative) happens inside the worker's
#: Phase 6 job under a different, write-scoped role. See
#: app/incidents/router.py's regenerate endpoint, which only enqueues.
#: No dev-password fallback -- see app/env.py and Phase 26.
API_READER_DATABASE_URL = require_env(
    "API_READER_DATABASE_URL", hint="see infra/.env.prod.example"
)

#: Still defaulted, deliberately: an unreachable Redis is a loud,
#: immediate connection error at the point of use, not a silent
#: connection under the wrong identity. It is a service address, not a
#: credential.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
