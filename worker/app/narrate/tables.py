"""The tables the narrator reads and the one it writes, as Core tables.

Here and not in app/db.py on purpose: a table defined in `app.narrate` can
be reached only by importing `app.narrate`, which no deterministic package
may do (worker/pyproject.toml) — so nothing downstream can read a
narration. They share app.db's metadata, and scripts/check_schema_drift.py
compares them with the API's (api/app/investigations/tables.py and
api/app/narrations/tables.py).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db import metadata

investigations = sa.Table(
    "investigations",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("closed_at", sa.DateTime(timezone=True)),
    sa.Column("environment", sa.Text, nullable=False),
    sa.Column("symptom", postgresql.JSONB, nullable=False),
    sa.Column("diagnosis", postgresql.JSONB),
    sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
)

investigation_readings = sa.Table(
    "investigation_readings",
    metadata,
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("id", sa.Text, nullable=False),
    sa.Column("reading", postgresql.JSONB, nullable=False),
)

hypotheses = sa.Table(
    "hypotheses",
    metadata,
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("id", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("reason", sa.Text),
    sa.Column("readings", postgresql.ARRAY(sa.Text), nullable=False),
)

fault_edges = sa.Table(
    "fault_edges",
    metadata,
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("id", sa.Integer, nullable=False),
    sa.Column("from_subject", sa.Text, nullable=False),
    sa.Column("to_subject", sa.Text, nullable=False),
    sa.Column("relation", sa.Text, nullable=False),
)

fault_edge_readings = sa.Table(
    "fault_edge_readings",
    metadata,
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("edge_id", sa.Integer, nullable=False),
    sa.Column("reading_id", sa.Text, nullable=False),
)

narrations = sa.Table(
    "narrations",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("attempt", sa.SmallInteger, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("prose", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("named", postgresql.ARRAY(sa.Text)),
    sa.Column("narrated_at", sa.DateTime(timezone=True), nullable=False),
    # The migration's: one row per attempt. Declared here too, so the
    # worker's own tests (metadata.create_all) hold it as the database does.
    sa.UniqueConstraint("investigation_id", "attempt", name="uq_narrations_attempt"),
    implicit_returning=False,
)
