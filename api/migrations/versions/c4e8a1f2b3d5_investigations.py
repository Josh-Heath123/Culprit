"""investigations: the walk's output, stored, with field 7's rule held by the database

Revision ID: c4e8a1f2b3d5
Revises: a9d2c40f7e18
Create Date: 2026-11-04 15:00:00.000000

Phase 32, part 2 (docs/DIAGNOSTIC_PLAN.md). `culprit diagnose` writes an
investigation (§2.8); this is where `POST /investigations` keeps it.

**Field 7's rule, held here and not only in code.** "A fault edge cannot be
created without at least one establishing reading" — and, as part 2's brief
adds, every reading an edge cites must belong to the same investigation.
Both are enforced by Postgres, so a writer that skips the model (a bug, a
hand-written INSERT, a future second ingest path) still cannot store a
narrative as a diagnosis:

- **No citation into another investigation.** An edge's citations are rows
  of `fault_edge_readings`, whose foreign key into `investigation_readings`
  is the composite `(investigation_id, reading_id)`. A reading id that
  exists only in some other investigation does not satisfy it.
- **No edge without a citation.** A constraint trigger, deferred to commit,
  refuses any `fault_edges` row with no `fault_edge_readings` row. Deferred,
  because the edge has to exist before the rows that cite it can reference
  it; checked at commit, so a transaction that inserts an edge and never
  cites anything for it fails as a whole. The trigger function is
  SECURITY DEFINER because `investigation-writer` holds INSERT and nothing
  else — it cannot SELECT the table the check reads — and the check must
  hold however little the writer can see.

**A new role, `investigation-writer`.** `.claude/rules/database.md`: add a
role, never widen one. An investigation is a diagnosis assembled from
readings — a different trust domain from the readings themselves
(`probe-writer`), from what a repository claims (`fact-writer`) and from
what an environment is configured to do (`capture-writer`). INSERT on the
five investigation tables and nothing else: not SELECT (the service uses
Core inserts with no RETURNING, as facts and readings do), not UPDATE, not
DELETE — an investigation, once stored, is a record.

**`api-reader` gains SELECT** on the five tables: the dashboard's reads.

**The incident tables become read-only (part 2, item 7).** An incident is
not an investigation — it has no readings, and an investigation's edges
must cite readings — so nothing is converted; `incident_candidates` and
`incident_anomalies` stay as history from the earlier engine until Phase 34
drops them. The correlation engine that wrote them is removed in this
phase, and no role keeps a write on them: `correlation-engine` loses
INSERT/UPDATE on `incident_candidates` and INSERT on `incident_anomalies`,
`root-cause-writer` loses UPDATE on `incident_candidates`. Reads stay.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a1f2b3d5"
down_revision: str | None = "a9d2c40f7e18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INVESTIGATION_WRITER_ROLE = "investigation-writer"
API_READER_ROLE = "api-reader"
CORRELATION_ENGINE_ROLE = "correlation-engine"
ROOT_CAUSE_WRITER_ROLE = "root-cause-writer"

TABLES = (
    "investigations",
    "hypotheses",
    "investigation_readings",
    "fault_edges",
    "fault_edge_readings",
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
        "investigations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("symptom", postgresql.JSONB(), nullable=False),
        sa.Column("root_subject", sa.Text()),
        sa.Column("complete", sa.Boolean()),
        sa.Column("diagnosis", postgresql.JSONB()),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "investigation_readings",
        sa.Column(
            "investigation_id",
            sa.Text(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("probe_id", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reading", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("investigation_id", "id"),
    )
    op.create_table(
        "hypotheses",
        sa.Column(
            "investigation_id",
            sa.Text(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("readings", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("investigation_id", "id"),
        sa.CheckConstraint(
            "status IN ('open', 'ruled_out', 'supported', 'unexplored')",
            name="ck_hypotheses_status",
        ),
    )
    op.create_table(
        "fault_edges",
        sa.Column(
            "investigation_id",
            sa.Text(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_subject", sa.Text(), nullable=False),
        sa.Column("to_subject", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("investigation_id", "id"),
        sa.CheckConstraint(
            "relation IN ('symptom_of', 'propagates_to', 'caused_by')",
            name="ck_fault_edges_relation",
        ),
        sa.CheckConstraint("from_subject <> to_subject", name="ck_fault_edges_distinct"),
    )
    op.create_table(
        "fault_edge_readings",
        sa.Column("investigation_id", sa.Text(), nullable=False),
        sa.Column("edge_id", sa.Integer(), nullable=False),
        sa.Column("reading_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("investigation_id", "edge_id", "reading_id"),
        sa.ForeignKeyConstraint(
            ["investigation_id", "edge_id"],
            ["fault_edges.investigation_id", "fault_edges.id"],
            ondelete="CASCADE",
            name="fk_fault_edge_readings_edge",
        ),
        # The composite key: a cited reading must be one *this*
        # investigation took.
        sa.ForeignKeyConstraint(
            ["investigation_id", "reading_id"],
            ["investigation_readings.investigation_id", "investigation_readings.id"],
            ondelete="CASCADE",
            name="fk_fault_edge_readings_reading",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION fault_edge_is_established() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        -- pg_temp named, and last: unnamed, Postgres searches it *first*,
        -- and a writer could shadow fault_edge_readings with a temp table
        -- holding a fake citation (found by the Phase 32 part 2 invariant
        -- audit). The table is schema-qualified as well, so neither alone
        -- has to hold.
        SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM public.fault_edge_readings
                WHERE investigation_id = NEW.investigation_id AND edge_id = NEW.id
            ) THEN
                RAISE EXCEPTION
                    'fault edge % of investigation % cites no reading: an edge with no '
                    'reading behind it is a narrative, not a diagnosis (DIAGNOSTIC_PLAN.md §2.8)',
                    NEW.id, NEW.investigation_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER fault_edge_needs_a_reading
        AFTER INSERT OR UPDATE ON fault_edges
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION fault_edge_is_established()
        """
    )

    password = _require_env("INVESTIGATION_WRITER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{INVESTIGATION_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{INVESTIGATION_WRITER_ROLE}"')
    for table in TABLES:
        op.execute(f'GRANT INSERT ON {table} TO "{INVESTIGATION_WRITER_ROLE}"')
        op.execute(f'GRANT SELECT ON {table} TO "{API_READER_ROLE}"')

    op.execute(f'REVOKE INSERT, UPDATE ON incident_candidates FROM "{CORRELATION_ENGINE_ROLE}"')
    op.execute(f'REVOKE INSERT ON incident_anomalies FROM "{CORRELATION_ENGINE_ROLE}"')
    op.execute(f'REVOKE UPDATE ON incident_candidates FROM "{ROOT_CAUSE_WRITER_ROLE}"')


def downgrade() -> None:
    op.execute(f'GRANT UPDATE ON incident_candidates TO "{ROOT_CAUSE_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT ON incident_anomalies TO "{CORRELATION_ENGINE_ROLE}"')
    op.execute(f'GRANT INSERT, UPDATE ON incident_candidates TO "{CORRELATION_ENGINE_ROLE}"')

    for table in reversed(TABLES):
        op.execute(f'REVOKE SELECT ON {table} FROM "{API_READER_ROLE}"')
        op.execute(f'REVOKE INSERT ON {table} FROM "{INVESTIGATION_WRITER_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{INVESTIGATION_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{INVESTIGATION_WRITER_ROLE}"')

    op.execute("DROP TRIGGER IF EXISTS fault_edge_needs_a_reading ON fault_edges")
    op.execute("DROP FUNCTION IF EXISTS fault_edge_is_established()")

    op.drop_table("fault_edge_readings")
    op.drop_table("fault_edges")
    op.drop_table("hypotheses")
    op.drop_table("investigation_readings")
    op.drop_table("investigations")
