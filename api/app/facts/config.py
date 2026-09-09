from app.env import require_env

#: fact-writer role (Phase 28) — INSERT on captures and intent_facts,
#: SELECT on captures. A new role rather than a widened one
#: (.claude/rules/database.md): an unattended CLI run authenticated by a
#: shared project token is a different trust domain from any of the
#: human-facing admin roles, and sharing a credential between them would
#: mean a leaked CI token could edit the service registry.
#: No dev-password fallback -- see app/env.py and Phase 26.
FACT_WRITER_DATABASE_URL = require_env(
    "FACT_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
