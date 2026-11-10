"""agents: when each agent last made a signed request — api-reader reads agent_nonces

Revision ID: e5b8a2d4c6f1
Revises: d7a3e5f1b9c2
Create Date: 2026-11-10

Phase 33 part 3: the agents screen shows, for every agent, when it last made
a request. The control plane already writes that moment, on every request an
agent's signature authenticates: the nonce it spends is inserted into
`agent_nonces` with `seen_at` (app/agents/dependencies.py). Nothing new is
written, and no role gains a write.

Two changes:

**1. The gateway's nonce cleanup keeps each agent's newest nonce.** It
already deletes nonces past their retention (2 x 300 s + 60 s). It now
spares the newest per agent, so that row's `seen_at` is the agent's last
signed request however long ago it was. The DELETE is the one
`agent-gateway` already runs, under the SELECT and DELETE it already holds;
only its predicate narrows. Keeping a spent nonce longer can only make a
replay *more* surely refused. That change is in the application; this
migration has nothing to do for it.

**2. `api-reader` gains SELECT on `agent_nonces`.** `GET /agents` is served
under `api-reader`, which already reads `agents`, `agent_allowances`,
`agent_tasks` and `agent_audit_log` for the same listing (d7a3e5f1b9c2). A
nonce row is an agent id, a random value already spent, and a time — nothing
a reader could use: a spent nonce is refused by the insert that recorded
it. This is a read grant on a table beside ones the role already reads, for
the same job, as `.claude/rules/database.md` and standing invariant 3 allow
— the third precedent after 635870479f4e and a9d2c40f7e18. The downgrade
revokes it. `api-reader` still writes nothing.

Refused requests are not recorded anywhere: a refusal is logged, never
stored, so a stranger cannot fill a table by sending bad signatures. The
screen says "last signed request" for that reason.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5b8a2d4c6f1"
down_revision: str | None = "d7a3e5f1b9c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_READER_ROLE = "api-reader"


def upgrade() -> None:
    op.execute(f'GRANT SELECT ON agent_nonces TO "{API_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON agent_nonces FROM "{API_READER_ROLE}"')
