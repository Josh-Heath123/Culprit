"""`verifications`, as a Core table (migrations/versions/f2b7d4e9a1c6_verifications.py).

Core rather than ORM for the reason app/investigations/tables.py gives:
`verification-writer` holds INSERT and nothing else, and the ORM's
INSERT ... RETURNING would need SELECT.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

verifications = sa.Table(
    "verifications",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("investigation_id", sa.Text, nullable=False),
    sa.Column("environment", sa.Text, nullable=False),
    sa.Column("verdict", sa.Text, nullable=False),
    sa.Column("failing_now_passes", sa.Boolean, nullable=False),
    sa.Column("no_regressions", sa.Boolean, nullable=False),
    sa.Column("changes_explained", sa.Boolean, nullable=False),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    # "planted" (a drill: the fault library, a quickstart) or "real".
    sa.Column("source", sa.Text, nullable=False),
    # "project-token", or "agent:<id>".
    sa.Column("submitted_by", sa.Text, nullable=False),
    sa.Column("verification", postgresql.JSONB, nullable=False),
    sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    implicit_returning=False,
)
