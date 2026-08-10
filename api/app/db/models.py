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

    Phase 18 adds `author_user_id` (who wrote it; ON DELETE SET NULL — a
    deleted user's postmortems survive), `updated_at` (set on every PATCH),
    and `embedded_at`/`embedding_error`, which together let the API/UI
    distinguish "queued" (both NULL) from "embedded" from "failed with
    this reason" — `embedding IS NULL` alone can't tell "never tried" from
    "tried and failed."
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
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # datetime | None, not datetime: the migrations declare this column
    # with only a server_default, no explicit NOT NULL — it's nullable at
    # the DB level (server_default fills it on insert, but doesn't change
    # the column's own nullability). Mapped[datetime] here used to claim
    # non-null and drifted from worker/app/db.py's Core definition until
    # scripts/check_schema_drift.py caught it.
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(timestamptz)
    embedded_at: Mapped[datetime | None] = mapped_column(timestamptz)
    embedding_error: Mapped[str | None]

    incident_candidate: Mapped["IncidentCandidate | None"] = relationship(
        back_populates="postmortems"
    )


class ObservedServiceEdge(Base):
    """A directed service-calls-service edge inferred from real trace data
    (Phase 19, Option A) — distinct from `ServiceDependency`, which is
    user-declared. `from_service`/`to_service` are plain strings, not FKs
    to `services.id`: an edge can legitimately point at a service Culprit
    hasn't registered yet, and that's useful information to surface, not
    an error to reject at insert time (see
    api/app/ingest_gateway/otlp_decode.py's decode_traces_request).

    Inference only *proposes* — accepting a suggestion is what actually
    inserts a `ServiceDependency` row (api/app/registry/service.py);
    nothing here ever changes correlation behaviour by itself.
    """

    __tablename__ = "observed_service_edges"

    from_service: Mapped[str] = mapped_column(primary_key=True)
    to_service: Mapped[str] = mapped_column(primary_key=True)
    observations: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    first_seen_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(timestamptz, server_default=text("now()"))
    dismissed_at: Mapped[datetime | None] = mapped_column(timestamptz)


class ArchitectureDecision(Base):
    """A human-written engineering decision (Phase 21,
    docs/AI_NATIVE_PLAN.md) — same shape as `Postmortem` (title, body,
    embedding, author, timestamps) minus the incident linkage, since a
    decision isn't tied to any one incident. Deliberately a sibling table,
    not a merge into `postmortems` — see AI_NATIVE_PLAN.md Phase 21 Known
    Trap 1.
    """

    __tablename__ = "architecture_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str]
    body: Mapped[str]
    embedding = mapped_column(Vector(1024), nullable=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(timestamptz)
    embedded_at: Mapped[datetime | None] = mapped_column(timestamptz)
    embedding_error: Mapped[str | None]


class AiChangeRecord(Base):
    """One row per commit made inside a Claude Code session (Phase 21,
    docs/AI_NATIVE_PLAN.md) — written automatically by
    `.claude/hooks/capture_ai_change.sh`, never by hand. `commit_sha` is
    unique so a hook re-fire or retry is a safe no-op, not a duplicate
    (see api/app/memory/service.py's create_ai_change_record). `author_
    user_id` stays NULL for hook-created rows — there's no reliable way to
    resolve a git identity to a Culprit user account automatically (see
    AI_NATIVE_PLAN.md Phase 21 Out of scope); `git_author` is the raw git
    identity string, always present since every commit has one.
    """

    __tablename__ = "ai_change_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    commit_sha: Mapped[str] = mapped_column(unique=True)
    summary: Mapped[str]
    files_changed: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    git_author: Mapped[str | None]
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    embedding = mapped_column(Vector(1024), nullable=True)
    committed_at: Mapped[datetime] = mapped_column(timestamptz)
    created_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))
    embedded_at: Mapped[datetime | None] = mapped_column(timestamptz)
    embedding_error: Mapped[str | None]


class InvariantViolation(Base):
    """One row per Phase 22 hook-time invariant violation (Phase 23,
    docs/AI_NATIVE_PLAN.md) — written by `.claude/hooks/check_invariants.sh`
    as a side effect of blocking (exit 2), never a replacement for it.
    `ai_change_record_id` stays NULL for every hook-time write: no commit
    exists yet at hook-fire time (Known Trap 1), so there's nothing to
    link to. A violation that never gets a linked commit — because the
    agent fixed it and the fixed version is what actually got committed —
    is the expected, correct outcome for most rows here, not a gap.
    """

    __tablename__ = "invariant_violations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    invariant_name: Mapped[str]
    file_paths: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    message: Mapped[str]
    detected_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))
    ai_change_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_change_records.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(
            "invariant_name IN ('migration_symmetry', 'coupled_files')",
            name="ck_invariant_violations_invariant_name",
        ),
    )


class IncidentChangeLink(Base):
    """Links an incident to an AI change record the worker's
    `link_recent_changes` cron job (Phase 23, docs/AI_NATIVE_PLAN.md)
    judged related — a fixed 30-minute lookback before the incident
    opened plus a deliberately crude service-name/file-path substring
    match (Known Trap 2). This only *annotates* an incident that already
    exists; it never changes which anomalies get grouped into which
    incident (worker/app/correlation/'s own concern, untouched).

    The composite primary key doubles as the idempotency guard
    `link_recent_changes`'s own `ON CONFLICT DO NOTHING` relies on (Known
    Trap 3) — the job re-scans recently-opened incidents every tick, so a
    duplicate insert attempt for the same (incident, change) pair is the
    normal case, not an error.
    """

    __tablename__ = "incident_change_links"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ai_change_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_change_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    linked_at: Mapped[datetime | None] = mapped_column(timestamptz, server_default=text("now()"))
    link_reason: Mapped[str]
