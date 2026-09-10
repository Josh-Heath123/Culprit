"""The `value_shape` CHECK constraint, against a real database.

Phase 28's half of the Phase 26.1 remediation (docs/HANDOFF.md §3, Q5).
`culprit_model.ValueShape` is the primary guarantee — the artefact it
protects is a capture bundle written to a file, which never reaches
Postgres. `ck_configured_facts_value_shape_is_closed` is defence in depth
behind it: the answer to "what if a future writer bypasses the model",
which is what the free-JSONB column had no answer to.

The tests that matter most are the ones that *attempt the attack*. The
Phase 27 invariant audit demonstrated that

    {"type": "url", "sample": "postgresql://u:hunter2@db/orders"}

inserted happily with no `grant_ref`. It does not any more, and the
proof is an INSERT that fails, not a reading of the migration.

Executed against a container, deliberately: a CHECK constraint is a
claim about a database, and the only way to check a claim about a
database is to make the database refuse something.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from culprit_model.shape import LengthClass, ValueFormat, ValueScheme, ValueShape, ValueType
from culprit_model.subjects import build
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

pytestmark = pytest.mark.asyncio

#: The payload from the Phase 27 audit.
LEAKED = "postgresql://u:hunter2@db/orders"


@pytest_asyncio.fixture
async def connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with db_engine.begin() as conn:
        yield conn


async def _capture(connection: AsyncConnection) -> uuid.UUID:
    capture_id = uuid.uuid4()
    await connection.execute(
        text(
            "INSERT INTO captures (id, plane, environment, extractor, started_at) "
            "VALUES (:id, 'CONFIGURED', 'staging', 'test@1', :now)"
        ),
        {"id": capture_id, "now": datetime.now(UTC)},
    )
    return capture_id


async def _insert(connection: AsyncConnection, **columns: object) -> None:
    capture_id = await _capture(connection)
    payload: dict[str, object] = {
        "id": uuid.uuid4(),
        "capture_id": capture_id,
        "environment": "staging",
        "subject": build("config", component="orders-svc", key="DATABASE_URL"),
        "predicate": "value_shape",
        "value": None,
        "value_shape": None,
        "grant_ref": None,
        "source_kind": "static",
        "extractor": "test@1",
        "artefact": None,
        "locator": None,
        "captured_at": datetime.now(UTC),
    }
    payload.update(columns)
    await connection.execute(
        text(
            "INSERT INTO configured_facts (id, capture_id, environment, subject, "
            "predicate, value, value_shape, grant_ref, source_kind, extractor, "
            "artefact, locator, captured_at) VALUES (:id, :capture_id, :environment, "
            ":subject, :predicate, CAST(:value AS jsonb), CAST(:value_shape AS jsonb), "
            ":grant_ref, :source_kind, :extractor, :artefact, :locator, :captured_at)"
        ),
        payload,
    )


async def test_the_audits_payload_is_now_refused(connection: AsyncConnection) -> None:
    """The exact thing that used to insert happily."""
    with pytest.raises(IntegrityError, match="value_shape_is_closed"):
        await _insert(
            connection,
            value_shape=f'{{"type": "url", "sample": "{LEAKED}"}}',
        )


async def test_an_extra_key_alongside_the_four_is_refused(
    connection: AsyncConnection,
) -> None:
    """Having all four required keys is not enough.

    The constraint is an exact key-set match, not a minimum. A "has these
    keys" check would have accepted `sample` sitting alongside them,
    which is precisely the payload above.
    """
    with pytest.raises(IntegrityError, match="value_shape_is_closed"):
        await _insert(
            connection,
            value_shape=(
                '{"type": "string", "length_class": "medium", "format": "dsn", '
                f'"present": true, "sample": "{LEAKED}"}}'
            ),
        )


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param('{"type": "not-a-type", "length_class": "medium", '
                     '"format": "dsn", "present": true}', id="unknown type"),
        pytest.param('{"type": "string", "length_class": "enormous", '
                     '"format": "dsn", "present": true}', id="unknown length class"),
        pytest.param('{"type": "string", "length_class": "medium", '
                     '"format": "postgres-dsn", "present": true}', id="unknown format"),
        pytest.param('{"type": "string", "length_class": "medium", '
                     '"format": "dsn", "present": "yes"}', id="present is not a bool"),
        # One per key. A missing key made the comparison SQL NULL, and a
        # CHECK constraint treats NULL as *satisfied* — so the first
        # version of this constraint let all four through. Every one is
        # asserted, not just the one that happened to be noticed.
        pytest.param('{"type": "string", "length_class": "medium", "format": "dsn"}',
                     id="missing present"),
        pytest.param('{"length_class": "medium", "format": "dsn", "present": true}',
                     id="missing type"),
        pytest.param('{"type": "string", "format": "dsn", "present": true}',
                     id="missing length_class"),
        pytest.param('{"type": "string", "length_class": "medium", "present": true}',
                     id="missing format"),
        pytest.param("{}", id="an empty object"),
        pytest.param('"a string, not an object"', id="not an object"),
    ],
)
async def test_a_malformed_shape_is_refused(
    connection: AsyncConnection, shape: str
) -> None:
    with pytest.raises(IntegrityError, match="value_shape_is_closed"):
        await _insert(connection, value_shape=shape)


async def test_a_null_shape_is_allowed(connection: AsyncConnection) -> None:
    """NULL means "no shape recorded", which is a legitimate state."""
    await _insert(connection, value_shape=None)


async def test_every_shape_culprit_model_can_produce_is_accepted(
    db_engine: AsyncEngine,
) -> None:
    """The constraint and the type must agree, member for member.

    Enumerated from `culprit_model` rather than restated, so adding an
    enum member without updating the migration fails here — a test
    failure rather than a production INSERT against a row the database
    cannot store. The migration writes the members out as literals
    because a migration must not import mutable application code
    (.claude/rules/database.md); this is what keeps that copy honest.
    """
    for value_type in ValueType:
        for length_class in LengthClass:
            for value_format in ValueFormat:
                shape = ValueShape(
                    type=value_type,
                    length_class=length_class,
                    format=value_format,
                    present=True,
                )
                async with db_engine.begin() as connection:
                    await _insert(connection, value_shape=shape.model_dump_json())


async def test_a_blank_grant_ref_is_refused(connection: AsyncConnection) -> None:
    """docs/HANDOFF.md §3 Q5's "related and cheaper" hole.

    Phase 26.1's constraint is `value IS NULL OR grant_ref IS NOT NULL`,
    and `grant_ref = ''` satisfies it. An empty string is not a grant.
    """
    with pytest.raises(IntegrityError, match="grant_ref_not_blank"):
        await _insert(connection, value=f'"{LEAKED}"', grant_ref="   ")


async def test_a_real_grant_still_permits_a_value(connection: AsyncConnection) -> None:
    """The opt-in path is a guard, not a prohibition."""
    await _insert(
        connection,
        value=f'"{LEAKED}"',
        grant_ref="config.read.values:DATABASE_URL",
        value_shape=ValueShape.of(LEAKED).model_dump_json(),
    )


async def test_an_ungranted_value_is_still_refused(connection: AsyncConnection) -> None:
    """Phase 26.1's own constraint, re-asserted here.

    Not redundant: this file's migration alters the same table, and a
    later change that dropped and recreated the constraints could lose
    this one without any other test noticing.
    """
    with pytest.raises(IntegrityError, match="value_requires_grant"):
        await _insert(connection, value=f'"{LEAKED}"')


# --- Phase 30: `scheme`, the optional fifth key (migration e4c1b7a9d2f0) ----


async def test_every_scheme_culprit_model_can_produce_is_accepted(
    db_engine: AsyncEngine,
) -> None:
    """Member for member, for the same reason as the test above — the
    migration writes the schemes out as literals, and this is what keeps
    that copy honest. Also why scripts/coupled_files.yaml pairs shape.py
    with e4c1b7a9d2f0 now."""
    for scheme in ValueScheme:
        shape = ValueShape(
            type=ValueType.STRING,
            length_class=LengthClass.MEDIUM,
            format=ValueFormat.URL,
            present=True,
            scheme=scheme,
        )
        async with db_engine.begin() as connection:
            await _insert(connection, value_shape=shape.model_dump_json())


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param(
            '{"type": "string", "length_class": "medium", "format": "dsn", '
            f'"present": true, "scheme": "{LEAKED}"}}',
            id="a DSN in scheme",
        ),
        pytest.param(
            '{"type": "string", "length_class": "medium", "format": "dsn", '
            '"present": true, "scheme": "cockroachdb"}',
            id="a scheme outside the closed set",
        ),
        pytest.param(
            '{"type": "string", "length_class": "medium", "format": "dsn", '
            f'"present": true, "scheme": "postgresql", "sample": "{LEAKED}"}}',
            id="a sixth key alongside the five",
        ),
    ],
)
async def test_scheme_is_closed_too(connection: AsyncConnection, shape: str) -> None:
    with pytest.raises(IntegrityError, match="value_shape_is_closed"):
        await _insert(connection, value_shape=shape)


async def test_a_shape_without_a_scheme_is_still_accepted(connection: AsyncConnection) -> None:
    """A protocol-1 extractor from before Phase 30 omits the key; that is
    a shape that did not classify its scheme, not a malformed one."""
    await _insert(
        connection,
        value_shape=(
            '{"type": "string", "length_class": "medium", "format": "dsn", "present": true}'
        ),
    )
