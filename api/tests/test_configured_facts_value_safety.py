"""Phase 26.1: an ungranted config value is unrepresentable in the database.

`.claude/rules/model.md` requires that facts carry config names and
shapes, never values, unless an explicit per-key grant applies — "and
there is a test asserting it". This is that test.

The point is *where* the rejection comes from. Phase 26 landed
`configured_facts` with a free-form `value` JSONB and nothing but
extractor discipline keeping a raw `DATABASE_URL` out of the one table
whose whole purpose is being safe to attach to a bug report. So every
insert here goes in as raw SQL through a superuser engine, bypassing the
ORM, any validation layer, and any future extractor: if these tests pass,
Postgres itself is the thing saying no, and no amount of carelessness
further up the stack can put an ungranted secret in this table.

docs/DIAGNOSTIC_PLAN.md §2.2; docs/HANDOFF.md §2, decision 2026-09-09.
"""

import pytest
import sqlalchemy as sa
from culprit_model.subjects import SubjectKind, build
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.asyncio

CONSTRAINT = "ck_configured_facts_value_requires_grant"

#: Built, not hand-formatted, even though this test never compares it
#: with a second source — `subjects.build()` is the only sanctioned
#: constructor (§2.3), and a literal here would be exempt from
#: scripts/tests/test_subject_construction.py only because `api/tests`
#: happens to be outside its scanned roots.
_SUBJECT = build(SubjectKind.CONFIG, component="orders-svc", key="DATABASE_URL")

_INSERT_CAPTURE = sa.text(
    "INSERT INTO captures (plane, environment, extractor, started_at) "
    "VALUES ('CONFIGURED', 'test-env', 'test-extractor@0.0.0', now()) "
    "RETURNING id"
)

_INSERT_FACT = sa.text(
    "INSERT INTO configured_facts "
    "(capture_id, environment, subject, predicate, value, value_shape, grant_ref, "
    " source_kind, extractor, captured_at) "
    "VALUES (:capture_id, 'test-env', :subject, 'value', "
    " CAST(:value AS jsonb), CAST(:value_shape AS jsonb), :grant_ref, "
    " 'introspection', 'test-extractor@0.0.0', now())"
)


async def _insert_fact(
    engine: AsyncEngine,
    *,
    value: str | None,
    value_shape: str | None = None,
    grant_ref: str | None = None,
) -> None:
    """Inserts one configured_fact without committing, so these tests
    leave the table as empty as they found it — `connect()` rather than
    `begin()` precisely so the implicit transaction is rolled back on
    close."""
    async with engine.connect() as conn:
        capture_id = (await conn.execute(_INSERT_CAPTURE)).scalar_one()
        await conn.execute(
            _INSERT_FACT,
            {
                "capture_id": capture_id,
                "subject": _SUBJECT,
                "value": value,
                "value_shape": value_shape,
                "grant_ref": grant_ref,
            },
        )


async def test_a_value_without_a_grant_is_rejected_by_the_database(
    db_engine: AsyncEngine,
) -> None:
    """The case the constraint exists for: an extractor writes the literal
    contents of a config key and names no grant."""
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_fact(
            db_engine,
            value='"postgresql://user:hunter2@db.internal:5432/orders"',
        )

    assert CONSTRAINT in str(excinfo.value)


async def test_json_null_is_not_a_way_around_the_constraint(
    db_engine: AsyncEngine,
) -> None:
    """`'null'::jsonb IS NULL` is false in SQL, which is why migration
    a3d81f6c4b27 had to drop this column's NOT NULL and its
    `'null'::jsonb` default rather than just adding the constraint on
    top. If that ever regresses, a row storing JSON null starts failing
    and the "no value" case stops being expressible at all."""
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_fact(db_engine, value="null")

    assert CONSTRAINT in str(excinfo.value)


async def test_a_shape_without_a_value_is_the_normal_case_and_is_allowed(
    db_engine: AsyncEngine,
) -> None:
    """What an extractor should be emitting: the shape of the key's
    contents, and no contents.

    The shape here changed in Phase 28 and the change is the point. This
    test used to assert
    `{"type": "url", "scheme": "postgresql", "host_resolves": true}` —
    §2.2's own illustrative example, and free-form JSONB, which is
    exactly the hole the Phase 27 audit demonstrated by inserting
    `{"type": "url", "sample": "postgresql://u:hunter2@db/orders"}` next
    to it with no grant. `ck_configured_facts_value_shape_is_closed` now
    admits only the four closed fields of `culprit_model.ValueShape`, so
    the old example is refused along with the attack it could not be told
    apart from. See api/tests/test_value_shape_constraint.py.
    """
    await _insert_fact(
        db_engine,
        value=None,
        value_shape=(
            '{"type": "string", "length_class": "medium", '
            '"format": "dsn", "present": true}'
        ),
    )


async def test_a_value_with_a_grant_is_allowed(db_engine: AsyncEngine) -> None:
    """The constraint is a gate, not a ban — an explicit per-key grant is
    the sanctioned way through it."""
    await _insert_fact(
        db_engine,
        value='"info"',
        grant_ref="grant:orders-svc/LOG_LEVEL",
    )


async def test_a_grant_without_a_value_is_allowed(db_engine: AsyncEngine) -> None:
    """Recording that a key was granted but reading it produced nothing
    is a legitimate state, not a constraint violation."""
    await _insert_fact(db_engine, value=None, grant_ref="grant:orders-svc/LOG_LEVEL")
