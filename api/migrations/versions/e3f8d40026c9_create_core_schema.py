"""create core schema

Revision ID: e3f8d40026c9
Revises:
Create Date: 2026-08-02 19:08:59.590921

"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3f8d40026c9"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: local dev already creates these via infra/postgres/init.sql,
    # but a migration shouldn't assume it's running against that init script
    # (e.g. a managed Timescale Cloud instance per the stack table).
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "raw_events",
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, nullable=False),
        sa.Column("service_name", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("event_type IN ('metric', 'log')", name="ck_raw_events_event_type"),
    )
    op.create_index(
        "ix_raw_events_service_name", "raw_events", ["service_name"]
    )
    op.create_index(
        "ix_raw_events_service_metric_time",
        "raw_events",
        ["service_name", "metric_name", "time"],
    )

    # Hypertable, partitioned on `time`. 1-day chunks suit a demo-scale
    # dataset with short-lived fault-injection bursts (Phase 2) better than
    # Timescale's 7-day default — it keeps compression/retention (see the
    # next migration) operating on many small chunks instead of a few huge
    # ones. The PK above is (time, id) because Timescale requires the
    # partitioning column in any unique/PK constraint on a hypertable.
    op.execute(
        "SELECT create_hypertable("
        "'raw_events', 'time', chunk_time_interval => INTERVAL '1 day'"
        ")"
    )

    op.create_table(
        "anomalies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("service_name", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_window", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_anomalies_service_name", "anomalies", ["service_name"]
    )
    op.create_index(
        "ix_anomalies_service_metric_detected",
        "anomalies",
        ["service_name", "metric_name", "detected_at"],
    )
    op.create_index(
        "ix_anomalies_time_window",
        "anomalies",
        ["time_window"],
        postgresql_using="gist",
    )

    op.create_table(
        "incident_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'resolved')",
            name="ck_incident_candidates_status",
        ),
    )

    op.create_table(
        "incident_anomalies",
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "anomaly_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("anomalies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "postmortems",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1024), nullable=True),
        sa.Column(
            "incident_candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incident_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_postmortems_embedding",
        "postmortems",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("postmortems")
    op.drop_table("incident_anomalies")
    op.drop_table("incident_candidates")
    op.drop_table("anomalies")
    op.drop_table("raw_events")
