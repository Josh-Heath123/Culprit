import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, text
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
    # BigInteger explicitly: migration 0001 declares this BIGINT + IDENTITY
    # (see api/migrations/versions/e3f8d40026c9_create_core_schema.py) —
    # bare `Mapped[int]` alone would default to INTEGER, which drifted
    # from the real column until scripts/check_schema_drift.py caught it.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
    # datetime | None, not datetime: the migrations declare this column
    # with only a server_default, no explicit NOT NULL — it's nullable at
    # the DB level (server_default fills it on insert, but doesn't change
    # the column's own nullability). Mapped[datetime] here used to claim
    # non-null and drifted from worker/app/db.py's Core definition until
    # scripts/check_schema_drift.py caught it.
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

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
    # datetime | None, not datetime: the migrations declare this column
    # with only a server_default, no explicit NOT NULL — it's nullable at
    # the DB level (server_default fills it on insert, but doesn't change
    # the column's own nullability). Mapped[datetime] here used to claim
    # non-null and drifted from worker/app/db.py's Core definition until
    # scripts/check_schema_drift.py caught it.
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

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


class Service(Base):
    """A registered service (Phase 14) — the source of truth for topology
    and monitored metrics, replacing the old hardcoded
    shared/culprit_shared/services.py dict (still present, but demo-only
    fixture data now — see that file's own docstring).

    `name` must match the OTel `service.name` resource attribute
    byte-for-byte (enforced at the API layer, not here — see
    api/app/registry/schemas.py). `monitored_metrics` empty ([]) means
    "score every metric seen for this service," not "score nothing" —
    see worker/app/anomaly/job.py.
    """

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    monitored_metrics: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: Soft delete: ingest starts rejecting this service's keys and the
    #: timeline stops showing it, but every historical raw_events/
    #: anomalies/incident_candidates row survives — see
    #: api/app/registry/service.py's delete().
    disabled_at: Mapped[datetime | None] = mapped_column(timestamptz)
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

    # passive_deletes=True: on a purge (app/registry/service.py's
    # delete_service with purge=True), let the FK's own
    # ON DELETE CASCADE (below, on ApiKey.service_id) remove the rows —
    # without this, SQLAlchemy's default cascade tries to UPDATE each
    # child's service_id to NULL before the parent delete, which violates
    # service_id's NOT NULL constraint instead of actually cascading.
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="service", passive_deletes=True
    )

    __table_args__ = (Index("ix_services_sort_order", "sort_order", "name"),)


class ServiceDependency(Base):
    """A directed service-calls-service edge, user-declared (Phase 14) —
    not inferred from trace data yet (that's Phase 19). Stored as one row
    per direction even though worker/app/correlation/graph.py currently
    treats the relation as symmetric, matching what real trace-derived
    inference will eventually produce anyway.
    """

    __tablename__ = "service_dependencies"

    from_service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), primary_key=True
    )
    to_service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "from_service_id <> to_service_id", name="ck_service_dependencies_no_self_edge"
        ),
    )


class User(Base):
    """A dashboard login (Phase 16) — replaces the single hardcoded
    operator (OPERATOR_USERNAME/OPERATOR_PASSWORD_HASH env vars) with a
    real table. Only `password_hash` (argon2) is ever stored; the
    plaintext password never reaches this model.

    `disabled_at` is read on every authenticated request, not just at
    login — see app/auth/dependencies.py's require_auth, which re-checks
    it (with a short in-process cache) so a disabled account's existing
    token stops working within that cache's TTL rather than being valid
    for its full remaining lifetime.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(server_default=text("'member'"))
    disabled_at: Mapped[datetime | None] = mapped_column(timestamptz)
    last_login_at: Mapped[datetime | None] = mapped_column(timestamptz)
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

    __table_args__ = (CheckConstraint("role IN ('admin', 'member')", name="ck_users_role"),)


class ApiKey(Base):
    """A scoped API key authenticating one service to ingest-gateway.

    Only the SHA-256 hash is stored; ingest-gateway hashes the presented
    key the same way and compares with secrets.compare_digest — the
    plaintext key never touches the database. `service_name` stays
    (ingest_gateway/auth.py returns it, and it's the value written to
    raw_events.service_name — removing it is a much larger change for no
    benefit) but is no longer unique on its own: `service_id` is the real
    FK, and dropping the old uniqueness is what makes key rotation
    possible (two live keys for one service during a cutover, one
    `revoked_at` and one not).
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    service_name: Mapped[str]
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="CASCADE")
    )
    key_hash: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str | None]
    revoked_at: Mapped[datetime | None] = mapped_column(timestamptz)
    last_used_at: Mapped[datetime | None] = mapped_column(timestamptz)
    # datetime | None, not datetime: the migrations declare this column
    # with only a server_default, no explicit NOT NULL — it's nullable at
    # the DB level (server_default fills it on insert, but doesn't change
    # the column's own nullability). Mapped[datetime] here used to claim
    # non-null and drifted from worker/app/db.py's Core definition until
    # scripts/check_schema_drift.py caught it.
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

    service: Mapped["Service"] = relationship(back_populates="api_keys")


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
    # datetime | None, not datetime: the migrations declare this column
    # with only a server_default, no explicit NOT NULL — it's nullable at
    # the DB level (server_default fills it on insert, but doesn't change
    # the column's own nullability). Mapped[datetime] here used to claim
    # non-null and drifted from worker/app/db.py's Core definition until
    # scripts/check_schema_drift.py caught it.
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))

    incident_candidate: Mapped["IncidentCandidate | None"] = relationship(
        back_populates="postmortems"
    )
