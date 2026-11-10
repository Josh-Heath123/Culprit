"""The verification writer's connection string — its own role, so a leaked
credential can append verifications and do nothing else, not even read
them back (migrations/versions/f2b7d4e9a1c6_verifications.py).
No dev-password fallback -- see app/env.py and Phase 26."""

from app.env import require_env

VERIFICATION_WRITER_DATABASE_URL = require_env(
    "VERIFICATION_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
