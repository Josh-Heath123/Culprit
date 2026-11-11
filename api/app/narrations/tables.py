"""`narrations`, as a Core table (migrations/versions/a6c2e9d4f8b1_narrations.py).

The API only reads it, through `api-reader`; the worker's narrator is the
one writer. Core, like the investigation tables beside it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

narrations = sa.Table(
    "narrations",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("attempt", sa.SmallInteger, nullable=False),
    # "complete", "failed" or "refused" — never pending.
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("prose", sa.Text),
    sa.Column("reason", sa.Text),
    sa.Column("named", postgresql.ARRAY(sa.Text)),
    sa.Column("narrated_at", sa.DateTime(timezone=True), nullable=False),
    implicit_returning=False,
)
