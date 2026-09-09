"""narrow configured_facts.value_shape, add the fact-writer role

Revision ID: d1f4a9c73b60
Revises: 7c2e94b1f0aa
Create Date: 2026-09-09 18:30:00.000000

Phase 28 (docs/DIAGNOSTIC_PLAN.md field 4 and field 9). Two changes that
share a migration because they are both about the same thing: making a
capture safe to write down.

**1. `value_shape` narrows from free JSONB.** Phase 26.1 closed
`configured_facts.value` and the Phase 27 invariant audit immediately
found the door next to it standing open: `value_shape`, the column the
design steers extractors *towards*, accepted

    {"type": "url", "sample": "postgresql://u:hunter2@db/orders"}

with no `grant_ref` and no complaint. §2.2 was narrowed at the time to
claim only what was true, and the real fix — a closed `ValueShape` type
in `shared/culprit_model/shape.py` — was scheduled here, because this is
where facts are first constructed and serialised for real.

That type is the primary enforcement point, deliberately: the artefact
the guarantee is about is a capture bundle written to a file and attached
to a bug report, which never reaches Postgres at all. This constraint is
defence in depth behind it — the answer to "what if a future writer
bypasses the model", which is exactly what the free-JSONB column had no
answer to.

The constraint is written as an exact key-set match rather than a
minimum: `value_shape - 'type' - ... = '{}'::jsonb` leaves nothing
behind, so an unknown fifth key fails. A `?&`-style "has these keys"
check would have accepted `sample` alongside them, which is precisely
the payload above.

Kept in step with `ValueShape` by `api/tests/test_value_shape_constraint.py`,
which reads the enum members out of `culprit_model` and asserts each one
is accepted by the live constraint — so adding a member to the type
without updating this migration fails a test rather than failing in
production against a row it cannot store.

**2. `intent_facts` gains `value_shape` and `grant_ref` too.**
`c07a5f31d8e4` gave those columns to `configured_facts` only, on the
reasonable assumption that shapes are an environment-capture concern.
They are not: an INTENT extractor reads `.env.example` and
`os.environ.get("PORT", "8000")` and has a shape to report about what a
key is *supposed* to hold — 32 of the 64 config facts `culprit intent`
produces against this repository are exactly that. Without the column
they were accepted by the API, written as `value = NULL`, and the shape
silently discarded while the response reported them stored. (Found by
the Phase 28 invariant audit.)

They arrive with the same two constraints `configured_facts` carries, for
the same reasons: a literal needs a grant, and a shape must be the closed
four-field form. `intent_facts` is now writable by an unattended CI
credential, so it needs the guarantee at least as much as the table that
is not yet written at all.

**3. A `fact-writer` role.** `POST /facts/captures` (field 9) is the
first thing that writes `captures`/`intent_facts`, and no existing role
can. Per `.claude/rules/database.md` that means a new role, not a wider
one: this is a genuinely new trust domain — an unattended CLI run in
somebody's CI, authenticated by a project token rather than a user
session — and giving `registry-admin` or `postmortem-writer` insert
rights on the fact tables would put a human-facing admin role and an
unattended one behind the same credential.

Grants are the minimum the endpoint needs: INSERT + SELECT on `captures`
(it inserts one and reads it back for the response), INSERT on
`intent_facts`, and nothing at all on `configured_facts`, `readings` or
`divergences` — those belong to Phases 30 and 31, and a role that can
already write them would make those phases' own grant decisions
invisible.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d1f4a9c73b60"
down_revision: str | None = "7c2e94b1f0aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACT_WRITER_ROLE = "fact-writer"

_VALUE_SHAPE_IS_CLOSED = "ck_configured_facts_value_shape_is_closed"
_GRANT_REF_NOT_BLANK = "ck_configured_facts_grant_ref_not_blank"
_INTENT_VALUE_REQUIRES_GRANT = "ck_intent_facts_value_requires_grant"
_INTENT_VALUE_SHAPE_IS_CLOSED = "ck_intent_facts_value_shape_is_closed"
_INTENT_GRANT_REF_NOT_BLANK = "ck_intent_facts_grant_ref_not_blank"

# Mirrors culprit_model.shape. Written out as literals rather than
# imported: a migration is a historical snapshot and must not import
# mutable application code (.claude/rules/database.md). The test named
# in the docstring is what keeps the copy honest.
_VALUE_TYPES = ("string", "integer", "number", "boolean", "list", "mapping", "null", "unknown")
_LENGTH_CLASSES = ("not_applicable", "empty", "short", "medium", "long")
_FORMATS = (
    "opaque",
    "url",
    "dsn",
    "email",
    "hostname",
    "ip_address",
    "port",
    "path",
    "duration",
    "booleanish",
    "numeric",
    "uuid",
    "json",
    "secret",
    "list",
    "not_applicable",
)


def _in_list(values: Sequence[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


# Every comparison is COALESCE'd, and that is load-bearing rather than
# defensive style. `value_shape->>'type'` is SQL NULL when the key is
# absent, `NULL IN (...)` is NULL, and a CHECK constraint treats NULL as
# *satisfied* — so without COALESCE a shape missing any of the four keys
# passed straight through. Found by a test that inserted
# `{"type":"string","length_class":"medium","format":"dsn"}` and expected
# a refusal it did not get. The subtraction below only proves there are
# no *extra* keys; these prove there are no missing ones.
_VALUE_SHAPE_CONDITION = f"""
value_shape IS NULL OR (
    jsonb_typeof(value_shape) = 'object'
    AND value_shape - 'type' - 'length_class' - 'format' - 'present' = '{{}}'::jsonb
    AND COALESCE(value_shape->>'type', '') IN ({_in_list(_VALUE_TYPES)})
    AND COALESCE(value_shape->>'length_class', '') IN ({_in_list(_LENGTH_CLASSES)})
    AND COALESCE(value_shape->>'format', '') IN ({_in_list(_FORMATS)})
    AND COALESCE(jsonb_typeof(value_shape->'present'), '') = 'boolean'
)
"""

# docs/HANDOFF.md §3 Q5, "related and cheaper": the Phase 26.1 constraint
# is `value IS NULL OR grant_ref IS NOT NULL`, and `grant_ref = ''`
# satisfies it. An empty string is not a grant. `culprit_model.Fact`
# refuses one too (a whitespace-only grant_ref included); this is the
# database saying the same thing.
# `btrim(x)` with one argument trims **spaces only**, so `grant_ref` set
# to a tab or a newline satisfied it — and carried an ungranted literal
# in with it. `Fact` uses Python's `.strip()`, which trims all
# whitespace, so the docstring's claim that the two say the same thing
# was false. A regex against `\s` makes it true. (Found by the Phase 28
# invariant audit, by inserting a tab-and-newline grant_ref alongside an
# ungranted DSN and watching it pass.)
_GRANT_REF_CONDITION = r"grant_ref IS NULL OR grant_ref !~ '^\s*$'"


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    # Any row already holding a shape this constraint would reject fails
    # here, naming the constraint. The table is empty until Phase 30
    # writes to it, so this runs on zero rows today -- which is the whole
    # reason it lands now rather than after a capture has stored one.
    op.create_check_constraint(
        _VALUE_SHAPE_IS_CLOSED,
        "configured_facts",
        _VALUE_SHAPE_CONDITION,
    )
    op.create_check_constraint(
        _GRANT_REF_NOT_BLANK,
        "configured_facts",
        _GRANT_REF_CONDITION,
    )

    # intent_facts gets the same two columns and the same three
    # constraints -- see this migration's docstring for why an INTENT
    # fact has a shape at all.
    op.add_column(
        "intent_facts",
        sa.Column("value_shape", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("intent_facts", sa.Column("grant_ref", sa.String(), nullable=True))
    # `value` on intent_facts is NOT NULL with a `'null'::jsonb` default
    # (c07a5f31d8e4), and `'null'::jsonb IS NULL` is false in SQL -- so
    # the grant constraint has to read JSON null as "no value", exactly
    # the subtlety a3d81f6c4b27 had to fix on the other table. Written
    # against `jsonb_typeof` rather than dropping the NOT NULL, because
    # unlike configured_facts this column is genuinely required: an
    # INTENT fact's value is its payload.
    op.create_check_constraint(
        _INTENT_VALUE_REQUIRES_GRANT,
        "intent_facts",
        "jsonb_typeof(value) = 'null' OR jsonb_typeof(value) = 'boolean' "
        "OR subject NOT LIKE 'config:%' OR grant_ref IS NOT NULL",
    )
    op.create_check_constraint(
        _INTENT_VALUE_SHAPE_IS_CLOSED,
        "intent_facts",
        _VALUE_SHAPE_CONDITION,
    )
    op.create_check_constraint(
        _INTENT_GRANT_REF_NOT_BLANK,
        "intent_facts",
        _GRANT_REF_CONDITION,
    )

    password = _require_env("FACT_WRITER_DB_PASSWORD")
    op.execute(f'CREATE ROLE "{FACT_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{FACT_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT, SELECT ON captures TO "{FACT_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT ON intent_facts TO "{FACT_WRITER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{FACT_WRITER_ROLE}"')
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{FACT_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{FACT_WRITER_ROLE}"')

    op.drop_constraint(_INTENT_GRANT_REF_NOT_BLANK, "intent_facts", type_="check")
    op.drop_constraint(_INTENT_VALUE_SHAPE_IS_CLOSED, "intent_facts", type_="check")
    op.drop_constraint(_INTENT_VALUE_REQUIRES_GRANT, "intent_facts", type_="check")
    # Dropping these loses data irrecoverably and silently: after this
    # migration `value_shape` is the payload of every config fact an
    # INTENT capture produces, so a down/up cycle succeeds and leaves
    # contentless facts behind. Back up first (scripts/backup.sh) -- the
    # same warning a3d81f6c4b27 carries about the other table.
    op.drop_column("intent_facts", "grant_ref")
    op.drop_column("intent_facts", "value_shape")

    op.drop_constraint(_GRANT_REF_NOT_BLANK, "configured_facts", type_="check")
    op.drop_constraint(_VALUE_SHAPE_IS_CLOSED, "configured_facts", type_="check")
