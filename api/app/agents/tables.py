"""The agent tables, as Core tables (migrations/versions/d7a3e5f1b9c2_agents.py).

Core rather than ORM for the reason app/investigations/tables.py gives: each
role holds exactly the privileges its statements need, and the ORM's
INSERT ... RETURNING would need SELECT where a role is denied it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

agent_pairing_codes = sa.Table(
    "agent_pairing_codes",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("code_hash", sa.Text, nullable=False),
    sa.Column("created_by", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("used_at", sa.DateTime(timezone=True)),
    sa.Column("used_by", sa.Text),
    # No INSERT ... RETURNING: SQLAlchemy would add one for the identity id,
    # and RETURNING needs SELECT, which agent-admin does not hold.
    implicit_returning=False,
)

agents = sa.Table(
    "agents",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("public_key", sa.LargeBinary, nullable=False),
    sa.Column("reported_grants", postgresql.JSONB, nullable=False),
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.Column("pairing_code_id", sa.BigInteger, nullable=False),
)

agent_allowances = sa.Table(
    "agent_allowances",
    metadata,
    sa.Column("agent_id", sa.Text, primary_key=True),
    sa.Column("environment", sa.Text, primary_key=True),
    sa.Column("grants", postgresql.ARRAY(sa.Text), nullable=False),
    sa.Column("updated_by", sa.Text, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)

agent_tasks = sa.Table(
    "agent_tasks",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("environment", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("spec", postgresql.JSONB, nullable=False),
    sa.Column("created_by", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("claimed_at", sa.DateTime(timezone=True)),
    sa.Column("allowance", postgresql.ARRAY(sa.Text)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("outcome", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("result", postgresql.JSONB),
    sa.Column("investigation_id", sa.Text),
)

agent_nonces = sa.Table(
    "agent_nonces",
    metadata,
    sa.Column("agent_id", sa.Text, primary_key=True),
    sa.Column("nonce", sa.Text, primary_key=True),
    sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
)

agent_audit_log = sa.Table(
    "agent_audit_log",
    metadata,
    sa.Column("agent_id", sa.Text, primary_key=True),
    sa.Column("seq", sa.BigInteger, primary_key=True),
    sa.Column("prev", sa.Text, nullable=False),
    sa.Column("hash", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column("probe_id", sa.Text),
    sa.Column("target", sa.Text),
    sa.Column("verdict", sa.Text),
    sa.Column("grants", postgresql.ARRAY(sa.Text), nullable=False),
    sa.Column("entry", sa.Text, nullable=False),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
)
