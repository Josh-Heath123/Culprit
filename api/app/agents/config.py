"""The agent roles' connection strings (migrations/versions/d7a3e5f1b9c2_agents.py).

One per write surface, so a leaked credential reaches only its own:
`agent-admin` what an admin does (pairing codes, allowances, revocation,
tasks), `agent-registrar` pairing and nothing else, `agent-gateway` what a
paired agent's signed requests do.
"""

from app.env import require_env

AGENT_ADMIN_DATABASE_URL = require_env(
    "AGENT_ADMIN_DATABASE_URL", hint="see infra/.env.prod.example"
)
AGENT_REGISTRAR_DATABASE_URL = require_env(
    "AGENT_REGISTRAR_DATABASE_URL", hint="see infra/.env.prod.example"
)
AGENT_GATEWAY_DATABASE_URL = require_env(
    "AGENT_GATEWAY_DATABASE_URL", hint="see infra/.env.prod.example"
)
