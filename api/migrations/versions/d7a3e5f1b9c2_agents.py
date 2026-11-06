"""agents: pairing, allowances, tasks, nonces and an audit log no role can rewrite

Revision ID: d7a3e5f1b9c2
Revises: c4e8a1f2b3d5
Create Date: 2026-11-06 10:00:00.000000

Phase 33, part 2 (docs/DIAGNOSTIC_PLAN.md): the agent meets the control
plane. An agent pairs with a single-use code, holds an Ed25519 key whose
public half is stored here, signs every request, claims tasks addressed to
it, and ships its audit log.

**Six tables.**
- `agents`: one row per paired agent — its public key, the grants it
  reported holding per environment, and when (if ever) it was revoked.
- `agent_pairing_codes`: single-use, expiring codes, **stored hashed**: the
  code itself is shown once, to the admin who made it.
- `agent_allowances`: per agent and environment, the grants the operator
  allows. Empty by default. The API holds it inside what the agent reports;
  the agent intersects it with its own configuration again.
- `agent_tasks`: a probe or a walk, addressed to one agent, with the
  allowance it was claimed under and how it ended.
- `agent_nonces`: every nonce a signed request has used, kept at least as
  long as a timestamp can be fresh, so a replay is refused.
- `agent_audit_log`: the agent's own chained log, shipped entry by entry.

**`agent_audit_log` cannot be rewritten.** No role holds UPDATE or DELETE on
it, and triggers refuse UPDATE, DELETE and TRUNCATE to everyone, the owner
included — a database rule, not a convention. A further trigger refuses an
INSERT that does not extend the agent's stored chain: its `seq` must be one
past the last, and its `prev` the last row's `hash` (the genesis value for
the first). The API checks each entry's own hash before it gets here.

**Three new roles, one per write surface** (`.claude/rules/database.md`:
add a role, never widen one):
- `agent-admin` — what an admin does: make pairing codes, set allowances,
  revoke an agent, address a task to it.
- `agent-registrar` — pairing: spend a code, insert the agent. Nothing an
  admin or a paired agent can do.
- `agent-gateway` — what a paired agent's signed requests do: look up its
  key, record nonces, read its allowance, claim and complete its tasks,
  append to its audit log.

`api-reader` gains SELECT on the four tables an admin reads through the API
— agents, allowances, tasks and the audit log (`GET /agents`, a task, an
agent's audit) — never the codes or the nonces. These are new tables of the
dashboard's own read surface, granted as each earlier phase's new tables were
(`c4e8a1f2b3d5` for the investigation tables): the job is the same, reading
what the dashboard shows, and no write is granted. The downgrade revokes it.

**`investigations.submitted_by`** records whether an agent or the project
token stored an investigation: `'project-token'` or `'agent:<id>'`. Rows
stored before this phase were all the project token's.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7a3e5f1b9c2"
down_revision: str | None = "c4e8a1f2b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ADMIN_ROLE = "agent-admin"
AGENT_REGISTRAR_ROLE = "agent-registrar"
AGENT_GATEWAY_ROLE = "agent-gateway"
API_READER_ROLE = "api-reader"

GENESIS = "0" * 64

#: (role, password variable). Created in this order, dropped in reverse.
ROLES = (
    (AGENT_ADMIN_ROLE, "AGENT_ADMIN_DB_PASSWORD"),
    (AGENT_REGISTRAR_ROLE, "AGENT_REGISTRAR_DB_PASSWORD"),
    (AGENT_GATEWAY_ROLE, "AGENT_GATEWAY_DB_PASSWORD"),
)

#: Every grant, as (privileges, table, role). Revoked in reverse.
GRANTS = (
    # INSERT only: the admin makes a code and never reads one back (no
    # RETURNING — app/agents/tables.py). USAGE on the identity column's
    # sequence is needed all the same: Postgres checks it when the default
    # draws the next id (shown by test_agents_api.py without it).
    ("INSERT", "agent_pairing_codes", AGENT_ADMIN_ROLE),
    ("USAGE", "SEQUENCE agent_pairing_codes_id_seq", AGENT_ADMIN_ROLE),
    ("SELECT", "agents", AGENT_ADMIN_ROLE),
    ("UPDATE (revoked_at)", "agents", AGENT_ADMIN_ROLE),
    ("SELECT, INSERT, UPDATE", "agent_allowances", AGENT_ADMIN_ROLE),
    ("INSERT", "agent_tasks", AGENT_ADMIN_ROLE),
    ("SELECT", "agent_pairing_codes", AGENT_REGISTRAR_ROLE),
    ("UPDATE (used_at, used_by)", "agent_pairing_codes", AGENT_REGISTRAR_ROLE),
    ("INSERT", "agents", AGENT_REGISTRAR_ROLE),
    ("SELECT", "agents", AGENT_GATEWAY_ROLE),
    ("SELECT, INSERT, DELETE", "agent_nonces", AGENT_GATEWAY_ROLE),
    ("SELECT", "agent_allowances", AGENT_GATEWAY_ROLE),
    ("SELECT", "agent_tasks", AGENT_GATEWAY_ROLE),
    (
        "UPDATE (claimed_at, allowance, completed_at, outcome, reason, result, investigation_id)",
        "agent_tasks",
        AGENT_GATEWAY_ROLE,
    ),
    ("SELECT, INSERT", "agent_audit_log", AGENT_GATEWAY_ROLE),
    ("SELECT", "agents", API_READER_ROLE),
    ("SELECT", "agent_allowances", API_READER_ROLE),
    ("SELECT", "agent_tasks", API_READER_ROLE),
    ("SELECT", "agent_audit_log", API_READER_ROLE),
)


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    op.create_table(
        "agent_pairing_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("code_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", sa.Text()),
        sa.CheckConstraint("char_length(code_hash) = 64", name="ck_agent_pairing_codes_hashed"),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("reported_grants", postgresql.JSONB(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "pairing_code_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_pairing_codes.id"),
            nullable=False,
            unique=True,
        ),
        sa.CheckConstraint("octet_length(public_key) = 32", name="ck_agents_ed25519_key"),
        sa.CheckConstraint("id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'", name="ck_agents_id_shape"),
    )
    op.create_table(
        "agent_allowances",
        sa.Column(
            "agent_id", sa.Text(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("grants", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("agent_id", "environment"),
    )
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "agent_id", sa.Text(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("allowance", postgresql.ARRAY(sa.Text())),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("investigation_id", sa.Text()),
        sa.CheckConstraint("kind IN ('probe', 'diagnose')", name="ck_agent_tasks_kind"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('completed', 'refused', 'error')",
            name="ck_agent_tasks_outcome",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR claimed_at IS NOT NULL", name="ck_agent_tasks_claimed_first"
        ),
    )
    op.create_index("ix_agent_tasks_unclaimed", "agent_tasks", ["agent_id", "created_at"])
    op.create_table(
        "agent_nonces",
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("agent_id", "nonce"),
    )
    op.create_index("ix_agent_nonces_seen_at", "agent_nonces", ["seen_at"])
    op.create_table(
        "agent_audit_log",
        sa.Column("agent_id", sa.Text(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("prev", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("probe_id", sa.Text()),
        sa.Column("target", sa.Text()),
        sa.Column("verdict", sa.Text()),
        sa.Column("grants", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("agent_id", "seq"),
        sa.UniqueConstraint("agent_id", "hash", name="uq_agent_audit_log_hash"),
        sa.CheckConstraint("seq >= 1", name="ck_agent_audit_log_seq"),
        sa.CheckConstraint("kind IN ('task', 'probe')", name="ck_agent_audit_log_kind"),
    )

    op.execute(
        """
        CREATE FUNCTION agent_audit_log_is_append_only() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            RAISE EXCEPTION
                'agent_audit_log is append-only: % is refused to every role, the owner included',
                TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_audit_log_no_update_or_delete
        BEFORE UPDATE OR DELETE ON agent_audit_log
        FOR EACH ROW EXECUTE FUNCTION agent_audit_log_is_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_audit_log_no_truncate
        BEFORE TRUNCATE ON agent_audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION agent_audit_log_is_append_only()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION agent_audit_log_extends_the_chain() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE
            last_seq bigint;
            last_hash text;
        BEGIN
            SELECT seq, hash INTO last_seq, last_hash FROM public.agent_audit_log
            WHERE agent_id = NEW.agent_id ORDER BY seq DESC LIMIT 1;
            IF last_seq IS NULL THEN
                last_seq := 0;
                last_hash := '{GENESIS}';
            END IF;
            IF NEW.seq <> last_seq + 1 OR NEW.prev <> last_hash THEN
                RAISE EXCEPTION
                    'audit entry % of agent % does not extend its stored chain (last %)',
                    NEW.seq, NEW.agent_id, last_seq
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_audit_log_extends
        BEFORE INSERT ON agent_audit_log
        FOR EACH ROW EXECUTE FUNCTION agent_audit_log_extends_the_chain()
        """
    )

    op.add_column(
        "investigations",
        sa.Column(
            "submitted_by", sa.Text(), nullable=False, server_default=sa.text("'project-token'")
        ),
    )
    op.create_check_constraint(
        "ck_investigations_submitted_by",
        "investigations",
        "submitted_by = 'project-token' "
        "OR submitted_by ~ '^agent:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
    )

    for role, variable in ROLES:
        password = _require_env(variable)
        op.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD {_pg_string_literal(password)}')
        op.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
    for privileges, table, role in GRANTS:
        op.execute(f'GRANT {privileges} ON {table} TO "{role}"')


def downgrade() -> None:
    for privileges, table, role in reversed(GRANTS):
        op.execute(f'REVOKE {privileges} ON {table} FROM "{role}"')
    for role, _variable in reversed(ROLES):
        op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
        op.execute(f'DROP ROLE IF EXISTS "{role}"')

    op.drop_constraint("ck_investigations_submitted_by", "investigations", type_="check")
    op.drop_column("investigations", "submitted_by")

    op.execute("DROP TRIGGER IF EXISTS agent_audit_log_extends ON agent_audit_log")
    op.execute("DROP FUNCTION IF EXISTS agent_audit_log_extends_the_chain()")
    op.execute("DROP TRIGGER IF EXISTS agent_audit_log_no_truncate ON agent_audit_log")
    op.execute("DROP TRIGGER IF EXISTS agent_audit_log_no_update_or_delete ON agent_audit_log")
    op.execute("DROP FUNCTION IF EXISTS agent_audit_log_is_append_only()")

    op.drop_table("agent_audit_log")
    op.drop_index("ix_agent_nonces_seen_at", table_name="agent_nonces")
    op.drop_table("agent_nonces")
    op.drop_index("ix_agent_tasks_unclaimed", table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_table("agent_allowances")
    op.drop_table("agents")
    op.drop_table("agent_pairing_codes")
