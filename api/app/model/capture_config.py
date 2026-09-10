from app.env import require_env

#: capture-writer role (Phase 30) — INSERT + SELECT on captures, INSERT on
#: configured_facts, and nothing else. A new role rather than a widened
#: `fact-writer`: what a running environment is configured to do —
#: production included — is a different trust domain from what a
#: repository says about itself, and `.claude/rules/database.md` names a
#: third role reuse as the signal the rule has stopped working. See
#: migration e4c1b7a9d2f0. No dev-password fallback (app/env.py, Phase 26).
CAPTURE_WRITER_DATABASE_URL = require_env(
    "CAPTURE_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
