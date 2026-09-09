"""system model: components, connections, contracts

Revision ID: 7c2e94b1f0aa
Revises: a3d81f6c4b27
Create Date: 2026-09-09 14:10:00.000000

Phase 27 (docs/DIAGNOSTIC_PLAN.md): the flat service registry becomes a
typed, directed model of components and connections.

**Why the shapes are what they are.**

1. `services` is **renamed** to `components`, not copied into it. A
   rename carries the primary key, every foreign key pointing at it
   (`api_keys.service_id`), and — the part that matters most here —
   every GRANT already held on it by `api-reader`, `correlation-engine`,
   `anomaly-detector`, `ingest-gateway` and `registry-admin`. Creating a
   new table and copying rows would silently drop all of that and require
   re-granting from memory, which is exactly how a least-privilege model
   quietly becomes wrong. Phase 27's first acceptance criterion is "an
   existing deployment upgrades with no service/dependency data loss";
   a rename is the only form of this migration where that is true by
   construction rather than by careful copying.

   `api_keys.service_id` keeps its name. Renaming it is a wider change
   than this phase names (field 5 lists what may be modified, and
   `api/app/ingest_gateway/` is not on it), and the FK follows the
   renamed table regardless. Noted in docs/LIMITS.md rather than left as
   a surprise.

2. `service_dependencies` genuinely cannot be renamed into `connections`:
   its primary key *is* `(from_service_id, to_service_id)`, and a
   connection's identity is `(from, to, kind)` — two components may
   legitimately be connected in more than one way (field 8). So
   `connections` is a new table, its rows built from
   `service_dependencies`, and the old table is dropped once they are
   across.

3. Every migrated connection gets `kind='http'`, `declared_by=
   'culprit_yaml'` and `criticality='unknown'`. Only the first of those
   is a guess about the world, and it is the right one for a registry
   whose only consumer was HTTP-service correlation. The other two are
   honest: `service_dependencies` recorded no provenance at all, so
   "declared, by a human, in the declarative source" is what every row in
   it meant; and nothing ever classified an edge as on the request path,
   so `unknown` is the true answer rather than a flattering guess. See
   docs/LIMITS.md.

4. `contracts` is created and stays **empty this phase** — Phase 27's
   field 17 says connections may carry a null `contract_id`, and no
   contract *content* exists until Phase 28. It therefore gets no grants,
   the same rule Phase 26 applied to `captures`/`intent_facts`/... :
   there is no component with a need yet, and granting ahead of the need
   is the move .claude/rules/database.md rules out.

**The downgrade loses information, and says so.** `components.kind`,
`environment_scope` and `labels`, and `connections.kind`, `contract_id`,
`declared_by` and `criticality` have nowhere to go in the old schema.
`service_dependencies`' primary key is the untyped `(from, to)` pair, so
several connections of different kinds between the same two components
have to collapse into one row: the `GROUP BY` in the downgrade's INSERT
is what does that, and without it the statement fails outright on a
duplicate key the moment any model uses more than one connection kind
between a pair. A subsequent re-upgrade then produces one `http`
connection per surviving pair — the round trip succeeds, and it is lossy.

Verified by mutation, not by inspection: removing that `GROUP BY` makes
`scripts/check_migration_round_trip.py` fail with exactly that duplicate
key, which is the whole point of standing invariant 8 existing.
`scripts/check_migration_symmetry.py` passes either way — it is
structural and cannot see a data-dependent defect. Documented in
docs/LIMITS.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7c2e94b1f0aa"
down_revision: str | None = "a3d81f6c4b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept as literal strings, not imported from culprit_model.graph:
#: standing invariant 4 — a migration is a historical snapshot and does
#: not import mutable application code. If the enum grows in a later
#: phase, that phase writes its own migration; this one must keep
#: describing the schema as it was on the day it ran.
_COMPONENT_KINDS = (
    "'service', 'frontend', 'database', 'queue', 'external_api', "
    "'job', 'cache', 'object_store'"
)
_CONNECTION_KINDS = "'http', 'grpc', 'sql', 'message', 'cache', 'dns', 'auth'"
_DECLARED_BY = "'culprit_yaml', 'inferred', 'accepted_suggestion'"
_CRITICALITIES = "'on_request_path', 'background', 'unknown'"
_CONTRACT_KINDS = "'http', 'grpc', 'sql', 'message', 'cache', 'dns', 'auth'"


def upgrade() -> None:
    # --- 1. services -> components ------------------------------------
    op.rename_table("services", "components")
    # The index came along with the table but kept its old name; rename
    # it too so a future reader of \d components isn't told about a
    # table that no longer exists.
    op.execute("ALTER INDEX ix_services_sort_order RENAME TO ix_components_sort_order")
    op.execute(
        "ALTER TABLE components RENAME CONSTRAINT services_pkey TO components_pkey"
    )
    op.execute(
        "ALTER TABLE components RENAME CONSTRAINT services_name_key TO components_name_key"
    )

    op.add_column(
        "components",
        sa.Column(
            "kind", sa.String(), nullable=False, server_default=sa.text("'service'")
        ),
    )
    op.add_column(
        "components",
        sa.Column(
            "environment_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "components",
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_components_kind", "components", f"kind IN ({_COMPONENT_KINDS})"
    )

    # --- 2. contracts --------------------------------------------------
    # Created empty and left empty (field 17). `facts` is the reference
    # to the intent facts describing the interface (field 7) — a JSONB
    # array of subject URIs rather than a foreign key, because an
    # intent_facts row is scoped to one capture and a contract outlives
    # any single capture of it.
    op.create_table(
        "contracts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("subject_prefix", sa.String(), nullable=False),
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"kind IN ({_CONTRACT_KINDS})", name="ck_contracts_kind"),
    )

    # --- 3. connections ------------------------------------------------
    op.create_table(
        "connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "from_component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False, server_default=sa.text("'http'")),
        # Nullable until Phase 28 populates it (field 17). ON DELETE SET
        # NULL, not CASCADE: deleting a contract must not delete the
        # connection it described — the connection still exists, it has
        # just stopped having a known interface.
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "declared_by",
            sa.String(),
            nullable=False,
            server_default=sa.text("'culprit_yaml'"),
        ),
        sa.Column(
            "criticality",
            sa.String(),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_component_id <> to_component_id", name="ck_connections_no_self_edge"
        ),
        sa.CheckConstraint(f"kind IN ({_CONNECTION_KINDS})", name="ck_connections_kind"),
        sa.CheckConstraint(
            f"declared_by IN ({_DECLARED_BY})", name="ck_connections_declared_by"
        ),
        sa.CheckConstraint(
            f"criticality IN ({_CRITICALITIES})", name="ck_connections_criticality"
        ),
        sa.UniqueConstraint(
            "from_component_id",
            "to_component_id",
            "kind",
            name="uq_connections_from_to_kind",
        ),
    )
    op.create_index(
        "ix_connections_from_component", "connections", ["from_component_id"]
    )
    op.create_index("ix_connections_to_component", "connections", ["to_component_id"])

    # --- 4. data migration --------------------------------------------
    # Every existing declared dependency becomes an http connection. The
    # self-edge filter is belt-and-braces: service_dependencies had its
    # own ck_service_dependencies_no_self_edge, so this can only matter
    # on a database where that constraint was dropped by hand.
    op.execute(
        """
        INSERT INTO connections
            (from_component_id, to_component_id, kind, declared_by, criticality, created_at)
        SELECT
            d.from_service_id,
            d.to_service_id,
            'http',
            'culprit_yaml',
            'unknown',
            COALESCE(d.created_at, now())
        FROM service_dependencies d
        WHERE d.from_service_id <> d.to_service_id
        ON CONFLICT ON CONSTRAINT uq_connections_from_to_kind DO NOTHING
        """
    )

    op.drop_table("service_dependencies")

    # --- 5. grants ------------------------------------------------------
    # Exactly the privileges each role already held on
    # service_dependencies (635870479f4e), carried across the rename.
    # This is not a widening: no role gains a table it could not
    # previously read or write, and no role gains a verb it did not have.
    # `components` needs no grants at all — the rename carried them.
    op.execute('GRANT SELECT ON connections TO "correlation-engine"')
    op.execute('GRANT SELECT ON connections TO "api-reader"')
    # mcp-reader held SELECT on service_dependencies (beab08d5f92f's
    # READABLE_TABLES). Omitting it here would silently take a read away
    # from the MCP tools — a rename must not quietly shrink a role any
    # more than it may quietly widen one.
    op.execute('GRANT SELECT ON connections TO "mcp-reader"')
    op.execute(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON connections TO "registry-admin"'
    )
    # `contracts` deliberately gets nothing — see the module docstring.


def downgrade() -> None:
    op.execute('REVOKE ALL PRIVILEGES ON connections FROM "registry-admin"')
    op.execute('REVOKE ALL PRIVILEGES ON connections FROM "mcp-reader"')
    op.execute('REVOKE ALL PRIVILEGES ON connections FROM "api-reader"')
    op.execute('REVOKE ALL PRIVILEGES ON connections FROM "correlation-engine"')

    op.create_table(
        "service_dependencies",
        sa.Column(
            "from_service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "to_service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_service_id <> to_service_id", name="ck_service_dependencies_no_self_edge"
        ),
    )

    # Lossy, and deliberately so — see the module docstring. The GROUP BY
    # is load-bearing, not tidiness: `service_dependencies`' PK is the
    # untyped (from, to) pair, so several connections of different kinds
    # between the same two components must collapse to one row here.
    # Without it this statement raises a duplicate-key violation on any
    # model that used more than one connection kind between a pair —
    # exactly the data the feature exists to represent — and the
    # downgrade would be unrunnable. ON CONFLICT DO NOTHING is kept as a
    # second line only; the GROUP BY is what actually prevents the
    # collision, confirmed by removing each in turn against
    # scripts/check_migration_round_trip.py.
    op.execute(
        """
        INSERT INTO service_dependencies (from_service_id, to_service_id, created_at)
        SELECT c.from_component_id, c.to_component_id, MIN(c.created_at)
        FROM connections c
        GROUP BY c.from_component_id, c.to_component_id
        ON CONFLICT DO NOTHING
        """
    )

    op.drop_index("ix_connections_to_component", table_name="connections")
    op.drop_index("ix_connections_from_component", table_name="connections")
    op.drop_table("connections")
    op.drop_table("contracts")

    op.drop_constraint("ck_components_kind", "components", type_="check")
    op.drop_column("components", "labels")
    op.drop_column("components", "environment_scope")
    op.drop_column("components", "kind")

    op.execute(
        "ALTER TABLE components RENAME CONSTRAINT components_name_key TO services_name_key"
    )
    op.execute(
        "ALTER TABLE components RENAME CONSTRAINT components_pkey TO services_pkey"
    )
    op.execute("ALTER INDEX ix_components_sort_order RENAME TO ix_services_sort_order")
    op.rename_table("components", "services")

    # The re-created service_dependencies is a new table object, so the
    # grants 635870479f4e put on the original are gone. Restore exactly
    # those, so a downgrade leaves the role model where it found it
    # rather than quietly stripping correlation's read access.
    op.execute('GRANT SELECT ON service_dependencies TO "correlation-engine"')
    op.execute('GRANT SELECT ON service_dependencies TO "api-reader"')
    op.execute('GRANT SELECT ON service_dependencies TO "mcp-reader"')
    op.execute(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON service_dependencies TO "registry-admin"'
    )
