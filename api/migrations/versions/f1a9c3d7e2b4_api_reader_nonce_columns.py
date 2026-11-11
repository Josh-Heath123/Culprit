"""agents: api-reader reads two columns of agent_nonces, not the nonces

Revision ID: f1a9c3d7e2b4
Revises: e5b8a2d4c6f1
Create Date: 2026-11-10

Phase 34 part 2, carried in (Q19, ruled 2026-11-10). e5b8a2d4c6f1 gave
`api-reader` SELECT on all of `agent_nonces` so the agents screen could show
when each agent last made a signed request. That screen reads two columns:
`agent_id` and `seen_at` (app/agents/service.py, `list_agents`). The
`nonce` column — a value already spent — was never needed, so the grant is
narrowed to the two columns the job uses: a column grant, as
`.claude/rules/database.md` prefers to a table one.

The table grant is revoked and the column grant made in one transaction,
so the agents screen never loses the read. The downgrade restores the table
grant e5b8a2d4c6f1 made.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a9c3d7e2b4"
down_revision: str | None = "e5b8a2d4c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_READER_ROLE = "api-reader"


def upgrade() -> None:
    op.execute(f'REVOKE SELECT ON agent_nonces FROM "{API_READER_ROLE}"')
    op.execute(f'GRANT SELECT (agent_id, seen_at) ON agent_nonces TO "{API_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT (agent_id, seen_at) ON agent_nonces FROM "{API_READER_ROLE}"')
    op.execute(f'GRANT SELECT ON agent_nonces TO "{API_READER_ROLE}"')
