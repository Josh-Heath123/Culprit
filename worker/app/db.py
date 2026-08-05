"""Minimal Core table definitions for the worker's own queries/inserts.

Deliberately not the api/ ORM models: worker and api are separate uv
projects with no shared internals (per CLAUDE.md), and the worker only
ever needs enough shape to SELECT/INSERT/UPDATE — it has no use for
relationships or the full model. Must stay column-compatible with
api/app/db/models.py; if that schema changes, update these too.
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID

metadata = sa.MetaData()

raw_events = sa.Table(
    "raw_events",
    metadata,
    sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
    # Deliberately NOT autoincrement=True: SQLAlchemy then tries to fetch
    # the generated identity value back (via RETURNING for a single-row
    # insert, or a pre-fetched nextval() on the sequence otherwise) —
    # both need privileges ingestion-writer intentionally doesn't have
    # (INSERT-only, per Phase 1/3's least-privilege design). Leaving this
    # as a plain composite PK column (with the resulting SQLAlchemy
    # warning about unspecified autoincrement) means `id` is simply
    # omitted from the INSERT entirely — Postgres's own IDENTITY default
    # handles it server-side, which is all the consumer ever needs.
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("service_name", sa.String(), nullable=False),
    sa.Column("event_type", sa.String(), nullable=False),
    sa.Column("metric_name", sa.String(), nullable=True),
    sa.Column("value", sa.Float(), nullable=True),
    sa.Column("message", sa.String(), nullable=True),
    sa.Column("attributes", JSONB(), nullable=False),
)

anomalies = sa.Table(
    "anomalies",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("service_name", sa.String(), nullable=False),
    sa.Column("metric_name", sa.String(), nullable=False),
    sa.Column("score", sa.Float(), nullable=False),
    sa.Column("threshold", sa.Float(), nullable=False),
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("time_window", TSTZRANGE(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

incident_candidates = sa.Table(
    "incident_candidates",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_anomaly_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    # Phase 6 (app/rag) — written once by generate_root_cause_narrative.
    sa.Column("root_cause_hypothesis", sa.String(), nullable=True),
    sa.Column("root_cause_confidence", sa.String(), nullable=True),
    sa.Column("root_cause_confidence_reason", sa.String(), nullable=True),
    sa.Column("root_cause_evidence", JSONB(), nullable=True),
    sa.Column("root_cause_generated_at", sa.DateTime(timezone=True), nullable=True),
)

incident_anomalies = sa.Table(
    "incident_anomalies",
    metadata,
    sa.Column("incident_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("anomaly_id", UUID(as_uuid=True), primary_key=True),
)

postmortems = sa.Table(
    "postmortems",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("body", sa.String(), nullable=False),
    sa.Column("embedding", Vector(1024), nullable=True),
    sa.Column("incident_candidate_id", UUID(as_uuid=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

# Phase 14: worker/app/correlation/job.py queries these two for adjacency
# (services.disabled_at, service_dependencies) — api_keys isn't mirrored
# here since nothing in worker ever queries it, per this file's own
# "only enough shape to SELECT/INSERT/UPDATE" principle above.
services = sa.Table(
    "services",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("name", sa.String(), nullable=False),
    sa.Column("display_name", sa.String(), nullable=True),
    sa.Column("sort_order", sa.Integer(), nullable=False),
    sa.Column("monitored_metrics", JSONB(), nullable=False),
    sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)

service_dependencies = sa.Table(
    "service_dependencies",
    metadata,
    sa.Column("from_service_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("to_service_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)
