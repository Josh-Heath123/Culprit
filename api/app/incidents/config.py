import os

#: api-reader role (Phase 1) — SELECT only on raw_events/anomalies/
#: incident_candidates/incident_anomalies/postmortems. Nothing in this
#: package ever writes to Postgres directly; the one write this phase
#: triggers (a new root-cause narrative) happens inside the worker's
#: Phase 6 job under a different, write-scoped role. See
#: app/incidents/router.py's regenerate endpoint, which only enqueues.
API_READER_DATABASE_URL = os.environ.get(
    "API_READER_DATABASE_URL",
    "postgresql+asyncpg://api-reader:api-reader-dev-password@localhost:5432/signalstack",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
