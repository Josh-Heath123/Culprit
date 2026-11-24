# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""The agent roles' connection strings (migrations/versions/d7a3e5f1b9c2_agents.py).

One per write surface, so a leaked credential reaches only its own:
`agent-admin` what an admin does (pairing codes, allowances, revocation,
tasks), `agent-registrar` pairing and nothing else, `agent-gateway` what a
paired agent's signed requests do.
"""

import os
from datetime import timedelta

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


def _task_deadline() -> timedelta:
    """How long a claimed task may stay open (F44-014): 15 minutes unless
    AGENT_TASK_DEADLINE_MINUTES says otherwise, a whole number above 0.

    No task kind declares a timeout of its own (the agent has a
    per-operation network timeout only), so one deadline, set on the
    server, holds every kind."""
    raw = os.environ.get("AGENT_TASK_DEADLINE_MINUTES", "15").strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise RuntimeError(
            f"AGENT_TASK_DEADLINE_MINUTES must be a whole number of minutes above 0, not {raw!r}"
        )
    return timedelta(minutes=int(raw))


TASK_DEADLINE = _task_deadline()
