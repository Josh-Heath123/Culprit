"""mcp reader role

Revision ID: beab08d5f92f
Revises: 8387f175770d
Create Date: 2026-08-10 21:51:29.330730

Phase 24 (docs/AI_NATIVE_PLAN.md): a new, dedicated, read-only role for
`mcp_server/` — the local stdio MCP server exposing Phase 21-23's data as
read-only tools a coding agent can call before making a change.

A new role rather than reusing `api-reader` — invariant 10's exception
case: this genuinely is a new trust domain (a process an agent's own
tooling talks to directly, outside the dashboard API's own request path),
not the same conceptual reader `api-reader` already serves. `mcp-reader`
gets SELECT only, on exactly the tables the four MCP tools read from — no
INSERT/UPDATE/DELETE anywhere (Out of scope: no write-capable tool exists
in this phase, so this role never needs write access to prove that at the
DB layer too).
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "beab08d5f92f"
down_revision: str | None = "8387f175770d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MCP_READER_ROLE = "mcp-reader"

READABLE_TABLES = (
    "postmortems",
    "architecture_decisions",
    "ai_change_records",
    "invariant_violations",
    "incident_change_links",
    "incident_candidates",
    "anomalies",
    "services",
    "service_dependencies",
)


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    password = _require_env("MCP_READER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{MCP_READER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{MCP_READER_ROLE}"')
    op.execute(f'GRANT SELECT ON {", ".join(READABLE_TABLES)} TO "{MCP_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{MCP_READER_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{MCP_READER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{MCP_READER_ROLE}"')
