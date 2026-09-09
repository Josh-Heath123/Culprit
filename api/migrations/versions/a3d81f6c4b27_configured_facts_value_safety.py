"""configured_facts value safety

Revision ID: a3d81f6c4b27
Revises: c07a5f31d8e4
Create Date: 2026-09-09 14:10:00.000000

Phase 26.1 (docs/HANDOFF.md §4), resolving Q3 from the Phase 26 invariant
audit. Recorded in docs/DIAGNOSTIC_PLAN.md §2.2.

`.claude/rules/model.md` requires that facts carry config names and
shapes, never values, unless an explicit per-key grant applies. Phase 26
landed `configured_facts` with a free-form `value` JSONB and nothing but
that convention standing between it and a raw `DATABASE_URL` — in the one
table whose whole purpose is being safe to attach to a bug report. This
makes the rule structural:

- `value_shape` is where a CONFIGURED fact about a config key belongs by
  default — type, length class, format class, e.g.
  `{"type": "url", "scheme": "postgresql", "host_resolves": true}`.
- `grant_ref` names the explicit per-key capability grant that permitted
  a literal value to be stored.
- The CHECK constraint makes an ungranted literal value unrepresentable
  *in `value`*, so a carelessly written extractor is rejected by Postgres
  rather than trusted to behave.

The scope of that guarantee is worth stating precisely, because it is
narrower than "this table cannot hold a secret": `value_shape` is
free-form JSONB and nothing stops an extractor putting a literal in
there instead. Constraining its key vocabulary is a real follow-up and
is deliberately not in this task's brief — see docs/HANDOFF.md §3.

One subtlety this migration has to fix rather than build on: c07a5f31d8e4
created `value` as NOT NULL with a `'null'::jsonb` server default, and
`'null'::jsonb IS NULL` is false in SQL. Adding the constraint from §2.2
verbatim on top of that column would make *every* row require a
`grant_ref` — the exact opposite of the intent. So `value` is dropped to
nullable and loses its default, and SQL NULL becomes the "no value
stored" state the constraint is written against.

The table is empty by design until Phase 27 (Phase 26 field 17), so this
runs on zero rows today. After Phase 30 captures start writing it, the
same change would be a migration over live data holding exactly the
credentials it is meant to exclude — which is why it lands now.

One asymmetry worth stating rather than discovering: `downgrade()` drops
`grant_ref`, so a *granted* literal value that goes down and back up
arrives at `upgrade()` indistinguishable from an ungranted one, and the
CHECK refuses to be created. That is the honest failure — the alternative
is either silently deleting an operator's data or silently keeping a
value whose grant no longer exists. Verified by round-tripping this
migration against a real database (upgrade -> downgrade -> upgrade) with
rows present; the ungranted/NULL population, which is every row this
table is designed to hold, round-trips clean.

The quieter half of the same asymmetry: `downgrade()` also drops
`value_shape`, which after Phase 27 is the actual payload of a CONFIGURED
fact. That loss is irrecoverable and, unlike the granted-value case
above, it does not announce itself — a down/up cycle succeeds and leaves
contentless facts behind. Back up before downgrading past this revision.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3d81f6c4b27"
down_revision: str | None = "c07a5f31d8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUE_REQUIRES_GRANT = "ck_configured_facts_value_requires_grant"


def upgrade() -> None:
    op.add_column(
        "configured_facts",
        sa.Column("value_shape", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "configured_facts",
        sa.Column("grant_ref", sa.String(), nullable=True),
    )

    # SQL NULL, not JSON null, is what the constraint below reads as
    # "no literal value stored" — see this migration's docstring.
    op.alter_column(
        "configured_facts",
        "value",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        server_default=None,
        existing_server_default=sa.text("'null'::jsonb"),
    )

    # JSON null was the old column's default — it meant "no value stored",
    # which is exactly what SQL NULL means under the new one. Purely a
    # change of representation, and the reason a downgrade/re-upgrade
    # cycle survives: without it, every row the downgrade below reset to
    # 'null'::jsonb would look like an ungranted literal value and the
    # constraint would refuse to be added.
    op.execute("UPDATE configured_facts SET value = NULL WHERE value = 'null'::jsonb")

    # Any row still holding a literal value without a grant fails here,
    # with Postgres naming the constraint. That is deliberate: no code
    # path, including this migration, gets to put an ungranted value in
    # this column quietly. (`value_shape` is not covered — see the
    # docstring.)
    op.create_check_constraint(
        _VALUE_REQUIRES_GRANT,
        "configured_facts",
        "value IS NULL OR grant_ref IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_VALUE_REQUIRES_GRANT, "configured_facts", type_="check")

    # Restoring NOT NULL requires every row to have a non-NULL value;
    # the pre-migration default was JSON null, so that is what rows
    # written under this migration are reset to.
    op.execute("UPDATE configured_facts SET value = 'null'::jsonb WHERE value IS NULL")
    op.alter_column(
        "configured_facts",
        "value",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'null'::jsonb"),
        existing_server_default=None,
    )

    op.drop_column("configured_facts", "grant_ref")
    op.drop_column("configured_facts", "value_shape")
