"""The five investigation tables, as Core tables.

Core, not ORM, for the reason app/readings/service.py gives: the ORM writes
with INSERT ... RETURNING, and Postgres requires SELECT to return anything,
so the writer would need a SELECT grant it is deliberately denied.
Mirrors migrations/versions/c4e8a1f2b3d5_investigations.py.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

investigations = sa.Table(
    "investigations",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("closed_at", sa.DateTime(timezone=True)),
    sa.Column("environment", sa.Text, nullable=False),
    sa.Column("symptom", postgresql.JSONB, nullable=False),
    sa.Column("root_subject", sa.Text),
    sa.Column("complete", sa.Boolean),
    sa.Column("diagnosis", postgresql.JSONB),
    sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
)

investigation_readings = sa.Table(
    "investigation_readings",
    metadata,
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("id", sa.Text, nullable=False),
    sa.Column("probe_id", sa.Text, nullable=False),
    sa.Column("target", sa.Text, nullable=False),
    sa.Column("verdict", sa.Text, nullable=False),
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
