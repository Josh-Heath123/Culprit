"""raw_events compression and retention

Revision ID: e2cab79bcc93
Revises: e3f8d40026c9
Create Date: 2026-08-02 19:09:00.436751

Demo-scale defaults (revisit once real ingestion volume exists):

- Compress chunks older than 7 days. `service_name` is the segment-by column
  (few distinct values, and it's the column every anomaly-scoring query
  filters on first) so compressed chunks stay fast to scan per-service.
- Drop chunks older than 30 days. That's comfortably longer than the 7-day
  compression cutoff and long enough to accumulate a handful of demo
  incidents/postmortems for RAG, without letting local disk grow unbounded
  across a multi-week demo.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2cab79bcc93"
down_revision: str | None = "e3f8d40026c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE raw_events SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'service_name', "
        "timescaledb.compress_orderby = 'time DESC'"
        ")"
    )
    op.execute("SELECT add_compression_policy('raw_events', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('raw_events', INTERVAL '30 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('raw_events', if_exists => true)")
    op.execute("SELECT remove_compression_policy('raw_events', if_exists => true)")
    op.execute("ALTER TABLE raw_events SET (timescaledb.compress = false)")
