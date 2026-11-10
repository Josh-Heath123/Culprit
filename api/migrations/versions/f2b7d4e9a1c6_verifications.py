"""verifications: an append-only record per verification, and a verify task

Revision ID: f2b7d4e9a1c6
Revises: f1a9c3d7e2b4
Create Date: 2026-11-10

Phase 34 part 2 (docs/DIAGNOSTIC_PLAN.md): outcomes in the control plane.

**`verifications`.** One row per verification `culprit verify` or an agent
made, pointing at the investigation it verified. The investigation is never
written to: whether it is verified is derived from its latest verification
("How Phase 34 is run": investigations stay final). The whole record, as
`culprit_model.verifications.Verification` validated it, is kept in
`verification`; the columns beside it are what the reads filter and sort
on. Two further columns say who stored it (`submitted_by`, as
`investigations.submitted_by` does) and whether the fault verified was
planted (a drill, the fault library) or happened on a real system
(`source`) — said by whoever asked for the verification, never guessed.

**Append-only, as `agent_audit_log` is.** No role holds UPDATE or DELETE,
and triggers refuse UPDATE, DELETE and TRUNCATE to every role, the owner
included. A later verification can disagree with an earlier one; it never
replaces it. A CHECK holds the one rule the type holds in both languages
at the database as well: `verified` only with all three clauses true.

**One new role, `verification-writer`** (`.claude/rules/database.md`: add a
role, never widen one): INSERT on `verifications`, nothing else — not even
SELECT, so the API checks what it needs under `api-reader` first.
`api-reader` gains SELECT on `verifications`, the dashboard's own read
surface (the investigation page, `GET /outcomes/accuracy`), as each earlier
phase's new tables were. The downgrade revokes both.

**`agent_tasks.kind` gains `verify`.** An agent verifies what it diagnosed.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b7d4e9a1c6"
down_revision: str | None = "f1a9c3d7e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERIFICATION_WRITER_ROLE = "verification-writer"
API_READER_ROLE = "api-reader"

VERDICTS = ("verified", "not_resolved", "regressed", "changed_underneath", "inconclusive")


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    op.create_table(
        "verifications",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Text(),
            sa.ForeignKey("investigations.id"),
            nullable=False,
        ),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("failing_now_passes", sa.Boolean(), nullable=False),
        sa.Column("no_regressions", sa.Boolean(), nullable=False),
        sa.Column("changes_explained", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("submitted_by", sa.Text(), nullable=False),
        sa.Column("verification", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id ~ '^ver-[0-9a-f]{16}$'", name="ck_verifications_id_shape"),
        sa.CheckConstraint(
            "verdict IN (" + ", ".join(f"'{v}'" for v in VERDICTS) + ")",
            name="ck_verifications_verdict",
        ),
        sa.CheckConstraint(
            "verdict <> 'verified' "
            "OR (failing_now_passes AND no_regressions AND changes_explained)",
            name="ck_verifications_verified_needs_every_clause",
        ),
        sa.CheckConstraint("source IN ('planted', 'real')", name="ck_verifications_source"),
        sa.CheckConstraint(
            "submitted_by = 'project-token' "
            "OR submitted_by ~ '^agent:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
            name="ck_verifications_submitted_by",
        ),
    )
    op.create_index(
        "ix_verifications_investigation", "verifications", ["investigation_id", "verified_at"]
    )

    op.execute(
        """
        CREATE FUNCTION verifications_are_append_only() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            RAISE EXCEPTION
                'verifications is append-only: % is refused to every role, the owner included',
                TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER verifications_no_update_or_delete
        BEFORE UPDATE OR DELETE ON verifications
        FOR EACH ROW EXECUTE FUNCTION verifications_are_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER verifications_no_truncate
        BEFORE TRUNCATE ON verifications
        FOR EACH STATEMENT EXECUTE FUNCTION verifications_are_append_only()
        """
    )

    op.drop_constraint("ck_agent_tasks_kind", "agent_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_tasks_kind", "agent_tasks", "kind IN ('probe', 'diagnose', 'verify')"
    )

    password = _require_env("VERIFICATION_WRITER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{VERIFICATION_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{VERIFICATION_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT ON verifications TO "{VERIFICATION_WRITER_ROLE}"')
    op.execute(f'GRANT SELECT ON verifications TO "{API_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON verifications FROM "{API_READER_ROLE}"')
    op.execute(f'REVOKE INSERT ON verifications FROM "{VERIFICATION_WRITER_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{VERIFICATION_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{VERIFICATION_WRITER_ROLE}"')

    # A verify task cannot survive the constraint without its kind: the
    # downgrade removes them with the kind (they were verifications' tasks).
    op.execute("DELETE FROM agent_tasks WHERE kind = 'verify'")
    op.drop_constraint("ck_agent_tasks_kind", "agent_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_tasks_kind", "agent_tasks", "kind IN ('probe', 'diagnose')"
    )

    op.execute("DROP TRIGGER IF EXISTS verifications_no_truncate ON verifications")
    op.execute("DROP TRIGGER IF EXISTS verifications_no_update_or_delete ON verifications")
    op.execute("DROP FUNCTION IF EXISTS verifications_are_append_only()")
    op.drop_index("ix_verifications_investigation", table_name="verifications")
    op.drop_table("verifications")
