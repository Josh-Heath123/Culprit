"""memory embedding hnsw indexes

Revision ID: b41c7d9e02a5
Revises: beab08d5f92f
Create Date: 2026-09-09 09:40:00.000000

Phase 26 (docs/DIAGNOSTIC_PLAN.md), truth repair.

`postmortems.embedding` has had an HNSW index since the very first
migration (e3f8d40026c9). Phase 21 added two sibling tables with the same
1024-dimension embedding column and the same cosine-similarity query
shape — `architecture_decisions` and `ai_change_records` — and did not
index either. `worker/app/rag/retrieval.py`'s UNION ALL and
`mcp_server/tools.py`'s `search_memory` therefore sequentially scan both,
which is invisible at eight fixture rows and is not at eight thousand.

Same index parameters as the existing one, deliberately: m=16 /
ef_construction=64 / vector_cosine_ops, because retrieval on all three
tables uses cosine distance and an index built for a different operator
class simply would not be used.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b41c7d9e02a5"
down_revision: str | None = "beab08d5f92f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HNSW_KWARGS = {
    "postgresql_using": "hnsw",
    "postgresql_with": {"m": 16, "ef_construction": 64},
}


def upgrade() -> None:
    op.create_index(
        "ix_architecture_decisions_embedding",
        "architecture_decisions",
        ["embedding"],
        postgresql_ops={"embedding": "vector_cosine_ops"},
        **_HNSW_KWARGS,
    )
    op.create_index(
        "ix_ai_change_records_embedding",
        "ai_change_records",
        ["embedding"],
        postgresql_ops={"embedding": "vector_cosine_ops"},
        **_HNSW_KWARGS,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_change_records_embedding", table_name="ai_change_records")
    op.drop_index("ix_architecture_decisions_embedding", table_name="architecture_decisions")
