"""narrations: one append-only record per narration attempt, and the narrator role

Revision ID: a6c2e9d4f8b1
Revises: f2b7d4e9a1c6
Create Date: 2026-11-11

Phase 35 part 2 (docs/DIAGNOSTIC_PLAN.md): the narrator.

**`narrations`.** The narrator (worker/app/narrate/) renders a stored
investigation into prose. Investigations are final, so a narration is its
own record, pointing at one (field 8, corrected 2026-11-11). Each attempt
is one row, written once with its final status — `complete` with its
prose, `failed` with a reason, or `refused` with what the prose named that
the investigation does not hold. There is no `pending`: a row exists only
when the attempt is over (2026-11-04). CHECKs hold what each status
carries, and `attempt` is 1 to 3 and unique per investigation, so a fourth
attempt cannot be committed however it is inserted.

**Append-only, as `verifications` is.** No role holds UPDATE or DELETE,
and triggers refuse UPDATE, DELETE and TRUNCATE to every role, the owner
included. A later attempt never replaces an earlier one; the newest stands.

**One new role, `narrator`** (standing invariant 3: a new job gets a new
role). SELECT on the five investigation tables, which it narrates, and on
`narrations`, to count its own attempts; INSERT on `narrations`. Nothing
else: it cannot write an investigation, a reading or a verification.

**`api-reader` gains SELECT on `narrations`.** A same-job read beside one
it already holds (standing invariant 3, clarified 2026-11-03): the
investigation page reads an investigation through `api-reader`, and its
narration is shown beside it, on the same page, by the same job. The API
runs the narration check again before serving prose. The downgrade revokes
every grant here.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6c2e9d4f8b1"
down_revision: str | None = "f2b7d4e9a1c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NARRATOR_ROLE = "narrator"
API_READER_ROLE = "api-reader"

#: What the narrator reads, besides its own narrations.
INVESTIGATION_TABLES = (
    "investigations",
    "investigation_readings",
    "hypotheses",
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
        "narrations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Text(),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prose", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("named", postgresql.ARRAY(sa.Text())),
        sa.Column(
            "narrated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id ~ '^nar-[0-9a-f]{16}$'", name="ck_narrations_id_shape"),
        sa.CheckConstraint("attempt BETWEEN 1 AND 3", name="ck_narrations_three_attempts"),
        sa.CheckConstraint(
            "provider ~ '^[a-z][a-z0-9-]{0,31}$'", name="ck_narrations_provider_shape"
        ),
        sa.CheckConstraint("length(model) BETWEEN 1 AND 200", name="ck_narrations_model_length"),
        sa.CheckConstraint(
            "(status = 'complete' AND prose IS NOT NULL AND length(prose) BETWEEN 1 AND 4000"
            " AND reason IS NULL AND named IS NULL)"
            " OR (status = 'failed' AND reason IS NOT NULL AND length(reason) BETWEEN 1 AND 500"
            " AND prose IS NULL AND named IS NULL)"
            " OR (status = 'refused' AND named IS NOT NULL AND cardinality(named) > 0"
            " AND prose IS NULL AND reason IS NULL)",
            name="ck_narrations_status_carries_its_own",
        ),
        sa.UniqueConstraint("investigation_id", "attempt", name="uq_narrations_attempt"),
    )

    op.execute(
        """
        CREATE FUNCTION narrations_are_append_only() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            RAISE EXCEPTION
                'narrations is append-only: % is refused to every role, the owner included',
                TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER narrations_no_update_or_delete
        BEFORE UPDATE OR DELETE ON narrations
        FOR EACH ROW EXECUTE FUNCTION narrations_are_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER narrations_no_truncate
        BEFORE TRUNCATE ON narrations
        FOR EACH STATEMENT EXECUTE FUNCTION narrations_are_append_only()
        """
    )

    password = _require_env("NARRATOR_DB_PASSWORD")
    op.execute(f'CREATE ROLE "{NARRATOR_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{NARRATOR_ROLE}"')
    for table in INVESTIGATION_TABLES:
        op.execute(f'GRANT SELECT ON {table} TO "{NARRATOR_ROLE}"')
    op.execute(f'GRANT SELECT, INSERT ON narrations TO "{NARRATOR_ROLE}"')
    op.execute(f'GRANT SELECT ON narrations TO "{API_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON narrations FROM "{API_READER_ROLE}"')
    op.execute(f'REVOKE SELECT, INSERT ON narrations FROM "{NARRATOR_ROLE}"')
    for table in INVESTIGATION_TABLES:
        op.execute(f'REVOKE SELECT ON {table} FROM "{NARRATOR_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{NARRATOR_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{NARRATOR_ROLE}"')

    op.execute("DROP TRIGGER IF EXISTS narrations_no_truncate ON narrations")
    op.execute("DROP TRIGGER IF EXISTS narrations_no_update_or_delete ON narrations")
    op.execute("DROP FUNCTION IF EXISTS narrations_are_append_only()")
    op.drop_table("narrations")
