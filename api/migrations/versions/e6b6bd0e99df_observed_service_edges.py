"""observed service edges

Revision ID: e6b6bd0e99df
Revises: 35b434e21f5c
Create Date: 2026-08-08 14:34:58.959526

Phase 19 (Option A only, docs/SELF_HOSTED_PLAN.md): service dependencies
stop being purely hand-declared (Phase 14's `service_dependencies`) and
gain a second, machine-observed source — directed edges inferred from
`CLIENT`-kind spans in real trace data, proposed to an admin for
confirmation rather than applied automatically (silently changing what
correlates is exactly the "wrong automated correlation" failure mode
CLAUDE.md names as the thing that makes this product untrustworthy).

`from_service`/`to_service` are plain TEXT, not FKs to `services.id`:
an edge can legitimately be observed pointing at a service Culprit
doesn't know about yet, and that's useful information ("you're calling
something Culprit hasn't registered"), not an error to reject at insert
time — see api/app/ingest_gateway/otlp_decode.py's decode_traces_request
and api/app/registry/service.py's suggestion-acceptance validation, which
is where an unregistered target actually gets refused (clearly, not
silently) rather than at the schema level.

No new DB role, unlike every schema-owning phase before this one: the
worker's existing `ingestion-writer` role (already INSERT-only on
raw_events for the same stream-drain job) gets SELECT+INSERT+UPDATE here
too — upserting edge counts is the same trust boundary as writing
raw_events, just a different table. SELECT is not optional here despite
this role otherwise being INSERT-only elsewhere: worker/app/consumer.py's
`_write_edges` does `INSERT ... ON CONFLICT DO UPDATE SET observations =
observed_service_edges.observations + excluded.observations`, and
Postgres requires SELECT on any column read by an ON CONFLICT DO UPDATE
expression — INSERT+UPDATE alone 403s with "permission denied for table
observed_service_edges" the moment a real conflict happens, which only
shows up under live traffic, not in a fresh-table smoke test. `api-reader`
gets SELECT (GET /services/topology/suggestions runs on it, same as every
other GET in app/registry/router.py). `registry-admin` gets SELECT+UPDATE
(accept reads a suggestion then writes to service_dependencies, which it
already has; dismiss sets dismissed_at) — never INSERT, since only the
worker's stream consumer ever creates rows here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b6bd0e99df"
down_revision: str | None = "35b434e21f5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INGESTION_WRITER = "ingestion-writer"
API_READER = "api-reader"
REGISTRY_ADMIN = "registry-admin"


def upgrade() -> None:
    op.create_table(
        "observed_service_edges",
        sa.Column("from_service", sa.String(), nullable=False, primary_key=True),
        sa.Column("to_service", sa.String(), nullable=False, primary_key=True),
        sa.Column("observations", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(f'GRANT SELECT, INSERT, UPDATE ON observed_service_edges TO "{INGESTION_WRITER}"')
    op.execute(f'GRANT SELECT ON observed_service_edges TO "{API_READER}"')
    op.execute(f'GRANT SELECT, UPDATE ON observed_service_edges TO "{REGISTRY_ADMIN}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT, UPDATE ON observed_service_edges FROM "{REGISTRY_ADMIN}"')
    op.execute(f'REVOKE SELECT ON observed_service_edges FROM "{API_READER}"')
    op.execute(f'REVOKE SELECT, INSERT, UPDATE ON observed_service_edges FROM "{INGESTION_WRITER}"')

    op.drop_table("observed_service_edges")
