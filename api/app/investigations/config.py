"""The investigation writer's connection string — its own role, so a
leaked credential can append investigations and do nothing else
(migrations/versions/c4e8a1f2b3d5_investigations.py)."""

from app.env import require_env

INVESTIGATION_WRITER_DATABASE_URL = require_env(
    "INVESTIGATION_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
