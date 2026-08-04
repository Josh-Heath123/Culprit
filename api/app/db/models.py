import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

timestamptz = DateTime(timezone=True)


class RawEvent(Base):
    """Metric points and log lines ingested from the demo services (Phase 3).

    A TimescaleDB hypertable partitioned on `time` (see migration 0001) —
    never query this without a time bound, per CLAUDE.md: it's high-volume
    by design and a table scan here is the mistake this project explicitly
    warns against.
    """

    __tablename__ = "raw_events"

    time: Mapped[datetime] = mapped_column(timestamptz, primary_key=True)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    service_name: Mapped[str] = mapped_column(index=True)
    event_type: Mapped[str]
    metric_name: Mapped[str | None]
    value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None]
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint("event_type IN ('metric', 'log')", name="ck_raw_events_event_type"),
        Index("ix_raw_events_service_metric_time", "service_name", "metric_name", "time"),
    )


class Anomaly(Base):
    """A single flagged deviation, scored deterministically by Phase 4.

    `time_window` + `service_name`/`metric_name` identifies the raw_events
    slice this was scored from. This is deliberately not a foreign key into
    raw_events: TimescaleDB advises against FKs referencing a hypertable,
    especially once compression is enabled (compressed chunks don't enforce
    row-level constraints the way normal tables do), and a range query is
    exactly what Phase 5's correlation step needs anyway.
    """

    __tablename__ = "anomalies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    service_name: Mapped[str] = mapped_column(index=True)
    metric_name: Mapped[str]
    score: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(timestamptz)
    time_window = mapped_column(TSTZRANGE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))

    incidents: Mapped[list["IncidentCandidate"]] = relationship(
        secondary="incident_anomalies", back_populates="anomalies"
    )

    __table_args__ = (
        Index("ix_anomalies_service_metric_detected", "service_name", "metric_name", "detected_at"),
        Index("ix_anomalies_time_window", "time_window", postgresql_using="gist"),
    )


class IncidentCandidate(Base):
    """A group of anomalies, across services, correlated into one incident
    by Phase 5's window-based rule engine (not this layer's concern)."""

    __tablename__ = "incident_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    opened_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))
    closed_at: Mapped[datetime | None] = mapped_column(timestamptz)
    #: Timestamp of the most recent anomaly attached to this incident
    #: (Phase 5). Closing is driven off this, not `created_at`/`opened_at`
    #: — an incident stays open as long as new correlated anomalies keep
    #: landing, regardless of when it was first opened.
    last_anomaly_at: Mapped[datetime] = mapped_column(timestamptz)
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))

    #: Root-cause narrative (Phase 6), written once by the RAG/LLM job
    #: triggered when this row is first created — see
    #: worker/app/rag/job.py. All nullable: a freshly-created incident has
    #: no narrative yet, and this column set is 1:1 with the incident, not
    #: a separate table, since there is exactly one narrative per incident.
    root_cause_hypothesis: Mapped[str | None]
    #: One of 'High' | 'Medium' | 'Low' (see ck_incident_candidates_root_cause_confidence).
    root_cause_confidence: Mapped[str | None]
    root_cause_confidence_reason: Mapped[str | None]
    #: Structured citations: [{"postmortem_id": ..., "postmortem_title": ..., "passage": ...}, ...]
    #: — never free text, so the narrative stays auditable per the Section 3 voice charter.
    root_cause_evidence: Mapped[list | None] = mapped_column(JSONB)
    root_cause_generated_at: Mapped[datetime | None] = mapped_column(timestamptz)

    anomalies: Mapped[list["Anomaly"]] = relationship(
        secondary="incident_anomalies", back_populates="incidents"
    )
    postmortems: Mapped[list["Postmortem"]] = relationship(back_populates="incident_candidate")

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved')",
            name="ck_incident_candidates_status",
        ),
        CheckConstraint(
            "root_cause_confidence IS NULL OR root_cause_confidence IN ('High', 'Medium', 'Low')",
            name="ck_incident_candidates_root_cause_confidence",
        ),
    )


class IncidentAnomaly(Base):
    """Join table linking an incident candidate to the anomalies it groups."""

    __tablename__ = "incident_anomalies"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    anomaly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("anomalies.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ApiKey(Base):
    """A scoped API key authenticating one demo service to ingest-gateway
    (Phase 3). Only the SHA-256 hash is stored; ingest-gateway hashes the
    presented key the same way and compares with secrets.compare_digest —
    the plaintext key never touches the database.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    service_name: Mapped[str] = mapped_column(unique=True)
    key_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))


class Postmortem(Base):
    """A past-incident writeup used as RAG context in Phase 6.

    `embedding` holds voyage-4 output (1024 dims, the model's default — see
    docs/IMPLEMENTATION_PLAN.md Section 7 on why voyage-4, not voyage-3.x)
    and is nullable because a postmortem can in principle be written before
    it's embedded. `incident_candidate_id` is nullable so seed postmortems
    (written before this system existed) can be loaded without a
    fabricated incident.
    """

    __tablename__ = "postmortems"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str]
    body: Mapped[str]
    embedding = mapped_column(Vector(1024), nullable=True)
    incident_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident_candidates.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))

    incident_candidate: Mapped["IncidentCandidate | None"] = relationship(
        back_populates="postmortems"
    )
