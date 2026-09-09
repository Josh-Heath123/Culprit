"""three plane schema

Revision ID: c07a5f31d8e4
Revises: b41c7d9e02a5
Create Date: 2026-09-09 09:45:00.000000

Phase 26 (docs/DIAGNOSTIC_PLAN.md §2.2, §2.5, §2.6): the INTENT /
CONFIGURED / OBSERVED tables, landed alongside the existing pipeline
without changing any of its behaviour.

**These tables are created empty and stay empty this phase** (Phase 26
field 17). Nothing writes them until Phase 28's extractors and Phase 31's
probes exist. That is also why no role is granted anything here: there is
no component with a need yet, and granting ahead of the need is exactly
the "widen a role now, justify it later" move .claude/rules/database.md
rules out. Phase 27 adds the grants along with the first reader.

Four shape decisions worth knowing, each encoding an invariant the
application would otherwise have to remember:

1. `intent_facts` has **no `environment` column**. INTENT is what the
   system is supposed to do, which is environment-independent by
   definition (§0.2) — a nullable column here would eventually get
   filled in by an extractor that had one handy, and every comparison
   against it would silently stop matching.
2. Neither fact table has a `plane` column: the table *is* the plane.
3. `configured_facts` has no `confidence_rank`. §2.4's ranks describe how
   much to trust a claim about what *should* be true; a reading of an
   actual environment isn't a claim of that kind.
4. `readings.reason` is `NOT NULL` when the verdict is `inconclusive` or
   `refused` (§2.6: "required when inconclusive or refused"), enforced by
   a check constraint rather than by whichever code path happens to write
   the row. "I could not check X because you have not granted Y" is a
   product feature; an unexplained `inconclusive` is a bug.

`readings` is a hypertable because it is evidence accumulating over time
and the queries against it are time-bounded. Retention is 90 days —
longer than `raw_events`' 30 (e2cab79bcc93), because a reading is
evidence for a verdict, not raw telemetry.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c07a5f31d8e4"
down_revision: str | None = "b41c7d9e02a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLANES = "'INTENT', 'CONFIGURED', 'OBSERVED'"
_SOURCE_KINDS = "'spec', 'introspection', 'static', 'test', 'assertion', 'observation'"
_VERDICTS = "'pass', 'fail', 'inconclusive', 'refused'"
_DIVERGENCE_KINDS = (
    "'intent_conflict', 'intent_vs_configured', 'intent_vs_observed', "
    "'configured_vs_observed', 'env_vs_env', 'baseline_deviation'"
)
_SEVERITIES = "'breaks_request_path', 'degrades', 'cosmetic', 'unknown'"
_DIVERGENCE_STATUSES = "'open', 'acknowledged', 'resolved', 'suppressed'"


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("plane", sa.String(), nullable=False),
        # Null for an INTENT capture, set for every other plane — the
        # same rule the two fact tables encode structurally, expressed
        # here as a check constraint because one table carries all three
        # planes.
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"plane IN ({_PLANES})", name="ck_captures_plane"),
        sa.CheckConstraint(
            "(plane = 'INTENT') = (environment IS NULL)",
            name="ck_captures_environment_matches_plane",
        ),
    )
    op.create_index("ix_captures_plane_started", "captures", ["plane", "started_at"])

    op.create_table(
        "intent_facts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "capture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("captures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("artefact", sa.String(), nullable=True),
        sa.Column("locator", sa.String(), nullable=True),
        sa.Column("confidence_rank", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"source_kind IN ({_SOURCE_KINDS})", name="ck_intent_facts_source_kind"
        ),
        sa.CheckConstraint(
            "confidence_rank BETWEEN 0 AND 100", name="ck_intent_facts_confidence_rank"
        ),
    )
    # Deliberately not unique on (capture_id, subject, predicate): two
    # INTENT facts about the same thing from two different sources is the
    # *input* to an intent_conflict divergence (§0.3), not a duplicate to
    # be rejected at insert time.
    op.create_index("ix_intent_facts_capture", "intent_facts", ["capture_id"])
    op.create_index("ix_intent_facts_subject", "intent_facts", ["subject", "predicate"])

    op.create_table(
        "configured_facts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "capture_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("captures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("artefact", sa.String(), nullable=True),
        sa.Column("locator", sa.String(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"source_kind IN ({_SOURCE_KINDS})", name="ck_configured_facts_source_kind"
        ),
    )
    op.create_index("ix_configured_facts_capture", "configured_facts", ["capture_id"])
    op.create_index(
        "ix_configured_facts_subject",
        "configured_facts",
        ["environment", "subject", "predicate"],
    )

    op.create_table(
        "readings",
        # (taken_at, id) composite PK for the same reason raw_events uses
        # (time, id): Timescale requires the partitioning column in any
        # unique or primary key constraint on a hypertable.
        sa.Column("taken_at", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("probe_id", sa.String(), nullable=False),
        sa.Column("probe_version", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column(
            "measured",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expected_source", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column(
            "grants_used",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.CheckConstraint(f"verdict IN ({_VERDICTS})", name="ck_readings_verdict"),
        sa.CheckConstraint(
            "verdict IN ('pass', 'fail') OR reason IS NOT NULL",
            name="ck_readings_reason_required_when_unresolved",
        ),
    )
    op.execute(
        "SELECT create_hypertable("
        "'readings', 'taken_at', chunk_time_interval => INTERVAL '1 day'"
        ")"
    )
    op.create_index("ix_readings_target", "readings", ["target", "taken_at"])
    op.create_index("ix_readings_probe", "readings", ["probe_id", "taken_at"])

    op.execute(
        "ALTER TABLE readings SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'probe_id', "
        "timescaledb.compress_orderby = 'taken_at DESC'"
        ")"
    )
    op.execute("SELECT add_compression_policy('readings', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('readings', INTERVAL '90 days')")

    op.create_table(
        "divergences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        # `left`/`right` are reserved words in Postgres; the model calls
        # these fields `left`/`right` (§2.5) and the mapping to
        # left_fact/right_fact lives in one place, api/app/db/models.py.
        # Whole Facts, not foreign keys: a divergence must stay readable
        # after the capture that produced its facts has been superseded.
        sa.Column("left_fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("right_fact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("environment", sa.String(), nullable=True),
        sa.Column(
            "severity", sa.String(), nullable=False, server_default=sa.text("'unknown'")
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default=sa.text("'open'")
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({_DIVERGENCE_KINDS})", name="ck_divergences_kind"),
        sa.CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_divergences_severity"),
        sa.CheckConstraint(
            f"status IN ({_DIVERGENCE_STATUSES})", name="ck_divergences_status"
        ),
    )
    op.create_index("ix_divergences_subject", "divergences", ["subject", "predicate"])
    op.create_index("ix_divergences_triage", "divergences", ["status", "severity"])


def downgrade() -> None:
    op.drop_table("divergences")

    op.execute("SELECT remove_retention_policy('readings', if_exists => true)")
    op.execute("SELECT remove_compression_policy('readings', if_exists => true)")
    op.execute("ALTER TABLE readings SET (timescaledb.compress = false)")
    op.drop_table("readings")

    op.drop_table("configured_facts")
    op.drop_table("intent_facts")
    op.drop_table("captures")
