# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""verifications: one investigation's fault is planted or real, never both

Revision ID: d1e5b9c3a7f2
Revises: a6c2e9d4f8b1
Create Date: 2026-11-24

Phase 44 batch 3, F44-041 (docs/FIELD_READINESS_PLAN.md §6).

POST /investigations/{id}/verifications looked up the source an
investigation's earlier verifications recorded, then stored the new one:
a check, then an insert, in two sessions. Two verifications posted at
once, labelled differently, both passed the check, and one investigation
was counted both planted and real in GET /outcomes/accuracy. The rule is
now the database's.

**An exclusion constraint, not a trigger.** `EXCLUDE USING gist
(investigation_id WITH =, source WITH <>)`: no two rows for one
investigation with different sources. A trigger that looked for an
existing row would not see the other transaction's uncommitted one and
would let both through; the constraint's index makes the second wait for
the first and then refuses it. Equality on text in a GiST index needs
`btree_gist`, a contrib extension Postgres trusts the database owner to
create; the image (timescaledb-ha) ships it.

**Existing rows are never altered or deleted.** `verifications` is
append-only (its triggers refuse UPDATE and DELETE to every role, the
owner included), and this migration would not change one if it could. If
any investigation already has verifications recorded both ways, the
upgrade stops before touching anything, saying how many, how to list
them, and that the choice is the operator's.

No grant changes. The downgrade drops the constraint and the extension.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e5b9c3a7f2"
down_revision: str | None = "a6c2e9d4f8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ex_verifications_one_source"

_BOTH_WAYS = (
    "SELECT investigation_id FROM verifications "
    "GROUP BY investigation_id HAVING count(DISTINCT source) > 1"
)


def upgrade() -> None:
    both = op.get_bind().execute(sa.text(f"SELECT count(*) FROM ({_BOTH_WAYS}) AS both_ways"))
    count = int(both.scalar_one())
    if count:
        raise RuntimeError(
            f"{count} investigation(s) already have verifications recorded both planted and "
            "real, so this migration cannot add the constraint that one investigation's fault "
            "is one or the other (F44-041). Nothing was changed: verifications is append-only, "
            "and this migration never alters or deletes a row. List them with:\n"
            f"  {_BOTH_WAYS};\n"
            "Stay on the previous release until you have decided what each one was, and raise "
            "it with the maintainers (docs/UPGRADING.md)."
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"ALTER TABLE verifications ADD CONSTRAINT {CONSTRAINT} "
        "EXCLUDE USING gist (investigation_id WITH =, source WITH <>)"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE verifications DROP CONSTRAINT {CONSTRAINT}")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
