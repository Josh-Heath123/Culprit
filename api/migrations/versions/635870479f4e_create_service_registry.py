"""create service registry

Revision ID: 635870479f4e
Revises: 528aa38b5971
Create Date: 2026-08-04 21:19:08.508174

Phase 14: services stop being a hardcoded dict
(shared/culprit_shared/services.py) and become rows in a table, with
api_keys gaining a real FK to them instead of just a bare service_name
string. See docs/SELF_HOSTED_PLAN.md's Phase 14 section for the full
spec this implements.

Order of operations matters here, in this exact sequence:
1. create `services` + `service_dependencies` (empty)
2. add the new nullable api_keys columns, drop the old
   service_name-must-be-unique constraint (rotation needs two live keys
   per service to be possible)
3. backfill: one `services` row per distinct api_keys.service_name, then
   point every existing api_keys row's service_id at it
4. only now make api_keys.service_id NOT NULL -- safe because every row
   was just backfilled (or the table is empty on a fresh install)
5. seed the demo adjacency edges, but only for services that actually
   got backfilled -- a fresh install with no demo keys set silently
   skips this (see 48c0b29fa215's own Phase-14 loosening: it no longer
   requires all three demo env vars, so a fresh api_keys table can
   legitimately be empty, or have anywhere from 0-3 demo rows)
6. grants, then the new registry-admin role

`ingest-gateway` already has SELECT on api_keys, granted by
5df76487a02f -- deliberately not re-touched here (granting it again
would be harmless, but revoking it on downgrade would incorrectly undo
a different, still-applied migration's guarantee). This migration only
grants/revokes what it itself introduces.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "635870479f4e"
down_revision: str | None = "528aa38b5971"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REGISTRY_ADMIN_ROLE = "registry-admin"

#: (from, to) directed pairs -- the exact edges
#: shared/culprit_shared/services.py's SERVICE_ADJACENCY already encodes
#: as a symmetric dict; stored here as two directed rows per pair to
#: match how worker/app/correlation/graph.py's _services_related reads
#: it (b in SERVICE_ADJACENCY.get(a)) and how Phase 19's real inference
#: will eventually produce directed edges anyway.
DEMO_ADJACENCY_PAIRS = [
    ("order-service", "inventory-service"),
    ("order-service", "payments-service"),
    ("inventory-service", "order-service"),
    ("payments-service", "order-service"),
]


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "monitored_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_services_sort_order", "services", ["sort_order", "name"])

    op.create_table(
        "service_dependencies",
        sa.Column(
            "from_service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "to_service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "from_service_id <> to_service_id", name="ck_service_dependencies_no_self_edge"
        ),
    )

    # Nullable for now -- service_id specifically stays nullable until
    # the backfill below has actually run; label/revoked_at/last_used_at
    # are nullable permanently (a key with no label, that's never been
    # revoked/used yet, is the normal case, not an edge case).
    op.add_column("api_keys", sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("api_keys", sa.Column("label", sa.String(), nullable=True))
    op.add_column("api_keys", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_api_keys_service_id_services",
        "api_keys",
        "services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The actual live constraint name, confirmed against the deployed
    # schema (\d api_keys) rather than guessed from the SQLAlchemy model
    # -- Postgres's auto-generated name happens to match the model's
    # `unique=True` convention here, but that's not guaranteed in general.
    op.drop_constraint("api_keys_service_name_key", "api_keys", type_="unique")

    # Backfill: one services row per distinct service_name already in
    # api_keys, then point every api_keys row at it. On a fresh install
    # with an empty api_keys table this is a no-op both times.
    op.execute(
        """
        INSERT INTO services (name, sort_order)
        SELECT service_name, row_number() OVER (ORDER BY created_at, service_name)
        FROM api_keys
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE api_keys SET service_id = s.id
        FROM services s
        WHERE s.name = api_keys.service_name
        """
    )
    op.alter_column("api_keys", "service_id", nullable=False)

    # Demo adjacency, only for services that actually exist post-backfill
    # -- reproduces today's exact SERVICE_ADJACENCY on culprit.co.za (all
    # three demo keys present), and is silently a no-op on a fresh
    # install with none of them.
    for from_name, to_name in DEMO_ADJACENCY_PAIRS:
        op.execute(
            f"""
            INSERT INTO service_dependencies (from_service_id, to_service_id)
            SELECT f.id, t.id FROM services f, services t
            WHERE f.name = {_pg_string_literal(from_name)}
              AND t.name = {_pg_string_literal(to_name)}
            ON CONFLICT DO NOTHING
            """
        )

    op.execute('GRANT SELECT ON services, service_dependencies TO "correlation-engine"')
    # api_keys too, not just services/service_dependencies: ServiceOut
    # (app/registry/schemas.py) includes each service's key metadata
    # (id/label/created_at/last_used_at/revoked, never key_hash), and
    # GET /services deliberately runs under api-reader, not
    # registry-admin (docs/SELF_HOSTED_PLAN.md Phase 14 step 4: "Registry
    # reads... may use api-reader; only writes need registry-admin") —
    # so api-reader needs read access to every table that response shape
    # touches.
    op.execute('GRANT SELECT ON services, service_dependencies, api_keys TO "api-reader"')
    op.execute('GRANT SELECT ON services TO "anomaly-detector"')
    op.execute('GRANT SELECT ON services TO "ingest-gateway"')

    registry_admin_password = _require_env("REGISTRY_ADMIN_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{REGISTRY_ADMIN_ROLE}" LOGIN PASSWORD '
        f"{_pg_string_literal(registry_admin_password)}"
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{REGISTRY_ADMIN_ROLE}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON services, service_dependencies, api_keys '
        f'TO "{REGISTRY_ADMIN_ROLE}"'
    )


def downgrade() -> None:
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{REGISTRY_ADMIN_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{REGISTRY_ADMIN_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{REGISTRY_ADMIN_ROLE}"')

    # Only revoke what this migration itself granted -- ingest-gateway's
    # SELECT on api_keys came from 5df76487a02f and stays untouched.
    op.execute('REVOKE SELECT ON services FROM "ingest-gateway"')
    op.execute('REVOKE SELECT ON services FROM "anomaly-detector"')
    op.execute('REVOKE SELECT ON services, service_dependencies, api_keys FROM "api-reader"')
    op.execute('REVOKE SELECT ON services, service_dependencies FROM "correlation-engine"')

    op.drop_constraint("fk_api_keys_service_id_services", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "last_used_at")
    op.drop_column("api_keys", "revoked_at")
    op.drop_column("api_keys", "label")
    op.drop_column("api_keys", "service_id")
    op.create_unique_constraint("api_keys_service_name_key", "api_keys", ["service_name"])

    op.drop_table("service_dependencies")
    op.drop_table("services")
