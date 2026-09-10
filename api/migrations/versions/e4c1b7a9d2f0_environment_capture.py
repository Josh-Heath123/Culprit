"""environment capture: value_shape.scheme, capture provenance, capture-writer

Revision ID: e4c1b7a9d2f0
Revises: b8e0c3d5f214
Create Date: 2026-09-10 12:00:00.000000

Phase 30 (docs/DIAGNOSTIC_PLAN.md) — the first phase that writes the
CONFIGURED plane. Four changes, all about the same thing: storing a
capture of a real environment so that what it says, and what it did *not*
look at, can both be read back.

**1. `value_shape` gains an optional `scheme`.** docs/HANDOFF.md §2
(2026-09-09, resolving Q7): "`ValueShape` carries `scheme` as a closed
enum, not a free string." A `DATABASE_URL` pointing at `postgresql://` in
staging and `mysql://` in production had identical shapes, so the most
consequential "pointing at the wrong thing" fault was invisible.

The two `*_value_shape_is_closed` constraints are rebuilt to allow a fifth
key, `scheme`, whose value must be in the closed set — the same exact
key-set match as before (`- 'scheme'` joins the subtraction), so a sixth
key still fails. `scheme` is *optional*: a shape written by a protocol-1
extractor before the field existed has four keys, and that is a shape
that did not classify its scheme, not a malformed one. A JSON `null`
scheme is accepted as the same statement, because that is what pydantic
serialises for an unclassified shape.

Kept in step with `culprit_model.shape.ValueScheme` by
`api/tests/test_value_shape_constraint.py`, which asserts every enum
member is accepted by the live constraint. `scripts/coupled_files.yaml`
now pairs `shape.py` with *this* file rather than with `d1f4a9c73b60`:
the vocabulary is defined by whichever migration last rebuilt the
constraint, and a historical migration is not edited to satisfy a
coupling check (.claude/rules/database.md — migrations are snapshots).

**2. `captures` gains `digest`, `signed_by`, `grants` and `refused`.**
Phase 30 field 7: "a capture is a signed, timestamped bundle of CONFIGURED
facts plus the grant set that produced it, so a reader can tell what was
*not* looked at." Phase 26's table can store the facts and the time. It
cannot store the other half — which is the half that makes a capture
honest. A capture of production that found no problem with the database
because it was never granted `db.metadata.read` must say so when it is
read back next month, not only when it was taken. All four are NULL for
an INTENT capture, which reads no environment and exercises no grant.

**3. A `capture-writer` role.** `POST /captures` is the first writer of
`configured_facts`. `.claude/rules/database.md`: add a role, never widen
one — and it names the signal plainly: "If you are about to add a third
[exception], that is the signal this rule has stopped working." Reusing
`fact-writer` would be exactly that third exception, and the trust
domains genuinely differ. `fact-writer` writes what a *repository* says,
from a CI run on a pull request; `capture-writer` writes what a *running
environment* is configured to do — production included. A credential
leaked from a fork's CI job should not be able to write claims about
production. Grants are the minimum: INSERT + SELECT on `captures` (it
checks for a duplicate and reads the row back), INSERT on
`configured_facts`, nothing else.

**4. `api-reader` gains SELECT on `captures` and `configured_facts`.**
For `GET /captures/{id}` and `GET /captures/diff`, which are dashboard
reads under a user session — `api-reader`'s domain, and the same step
Phase 27 took for `connections`. `configured_facts.value` can hold a
literal where an explicit per-key grant allowed one, so this is argued
rather than assumed: the API's single serialiser for a stored fact never
renders `value` for a `config:` subject (`app/model/captures.py`), the
same rule the CLI's report renderer enforces, and the test for that
endpoint plants a granted value and asserts it never appears.
"""
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e4c1b7a9d2f0"
down_revision: str | None = "b8e0c3d5f214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAPTURE_WRITER_ROLE = "capture-writer"
API_READER_ROLE = "api-reader"

_CONFIGURED_SHAPE = "ck_configured_facts_value_shape_is_closed"
_INTENT_SHAPE = "ck_intent_facts_value_shape_is_closed"

# Mirrors culprit_model.shape. Written out as literals, not imported: a
# migration is a historical snapshot and must not import mutable
# application code (.claude/rules/database.md). The test named in the
# docstring keeps the copy honest.
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
_SCHEMES = (
    "not_applicable",
    "postgresql",
    "mysql",
    "mariadb",
    "sqlite",
    "mssql",
    "oracle",
    "mongodb",
    "redis",
    "rediss",
    "memcached",
    "amqp",
    "amqps",
    "kafka",
    "nats",
    "http",
    "https",
    "ws",
    "wss",
    "grpc",
    "ftp",
    "sftp",
    "s3",
    "gs",
    "file",
    "ldap",
    "ldaps",
    "smtp",
    "smtps",
    "other",
)


def _in_list(values: Sequence[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


# The four-key condition exactly as d1f4a9c73b60 wrote it, for the
# downgrade to put back. Every comparison COALESCE'd for the reason that
# migration gives: `->>` of a missing key is SQL NULL, and a CHECK treats
# NULL as satisfied.
_FOUR_KEY_CONDITION = f"""
value_shape IS NULL OR (
    jsonb_typeof(value_shape) = 'object'
    AND value_shape - 'type' - 'length_class' - 'format' - 'present' = '{{}}'::jsonb
    AND COALESCE(value_shape->>'type', '') IN ({_in_list(_VALUE_TYPES)})
    AND COALESCE(value_shape->>'length_class', '') IN ({_in_list(_LENGTH_CLASSES)})
    AND COALESCE(value_shape->>'format', '') IN ({_in_list(_FORMATS)})
    AND COALESCE(jsonb_typeof(value_shape->'present'), '') = 'boolean'
)
"""

# The same, plus an optional `scheme`. `- 'scheme'` joins the subtraction
# so a sixth key still fails; the COALESCE to 'not_applicable' is what
# makes "no scheme key" and `"scheme": null` both mean "not classified",
# while any *present* string must be in the closed set.
_FIVE_KEY_CONDITION = f"""
value_shape IS NULL OR (
    jsonb_typeof(value_shape) = 'object'
    AND value_shape - 'type' - 'length_class' - 'format' - 'present' - 'scheme' = '{{}}'::jsonb
    AND COALESCE(value_shape->>'type', '') IN ({_in_list(_VALUE_TYPES)})
    AND COALESCE(value_shape->>'length_class', '') IN ({_in_list(_LENGTH_CLASSES)})
    AND COALESCE(value_shape->>'format', '') IN ({_in_list(_FORMATS)})
    AND COALESCE(jsonb_typeof(value_shape->'present'), '') = 'boolean'
    AND COALESCE(value_shape->>'scheme', 'not_applicable') IN ({_in_list(_SCHEMES)})
)
"""


def _pg_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in the environment to run this migration")
    return value


def upgrade() -> None:
    for table, name in (("configured_facts", _CONFIGURED_SHAPE), ("intent_facts", _INTENT_SHAPE)):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _FIVE_KEY_CONDITION)

    # NULL for an INTENT capture. `digest` is the SHA-256 of the exact
    # payload bytes the client sealed, recomputed by the API on receipt;
    # `signed_by` is the key id of a verified Ed25519 signature, NULL when
    # the capture was not signed.
    op.add_column("captures", sa.Column("digest", sa.String(), nullable=True))
    op.add_column("captures", sa.Column("signed_by", sa.String(), nullable=True))
    op.add_column(
        "captures",
        sa.Column("grants", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "captures",
        sa.Column("refused", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    password = _require_env("CAPTURE_WRITER_DB_PASSWORD")
    op.execute(
        f'CREATE ROLE "{CAPTURE_WRITER_ROLE}" LOGIN PASSWORD {_pg_string_literal(password)}'
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{CAPTURE_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT, SELECT ON captures TO "{CAPTURE_WRITER_ROLE}"')
    op.execute(f'GRANT INSERT ON configured_facts TO "{CAPTURE_WRITER_ROLE}"')

    op.execute(f'GRANT SELECT ON captures, configured_facts TO "{API_READER_ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON captures, configured_facts FROM "{API_READER_ROLE}"')

    op.execute(
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{CAPTURE_WRITER_ROLE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{CAPTURE_WRITER_ROLE}"')
    op.execute(f'DROP ROLE IF EXISTS "{CAPTURE_WRITER_ROLE}"')

    # Loses the grant set and the refusal list of every stored capture,
    # silently: after the downgrade a capture no longer says what it did
    # not look at. Back up first (scripts/backup.sh).
    op.drop_column("captures", "refused")
    op.drop_column("captures", "grants")
    op.drop_column("captures", "signed_by")
    op.drop_column("captures", "digest")

    # The four-key constraint refuses a fifth key, so every stored scheme
    # is stripped before it goes back. That is a real loss — the
    # postgresql-against-mysql distinction disappears from stored shapes —
    # and it is the only way the older constraint can be recreated over
    # rows the newer one allowed. The alternative, a downgrade that fails
    # on the first shape carrying a scheme, would leave the database
    # half-downgraded. `invariant 8`'s round-trip gate seeds such a row
    # (scripts/check_migration_round_trip.py) so this path runs for real.
    for table, name in (("configured_facts", _CONFIGURED_SHAPE), ("intent_facts", _INTENT_SHAPE)):
        op.execute(
            f"UPDATE {table} SET value_shape = value_shape - 'scheme' "
            "WHERE value_shape IS NOT NULL AND value_shape ? 'scheme'"
        )
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, _FOUR_KEY_CONDITION)
