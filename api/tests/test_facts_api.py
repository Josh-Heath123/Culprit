"""`POST /facts/captures` (Phase 28 field 9), against a real database.

Drives the router through FastAPI's TestClient under the real
`fact-writer` role, not the container superuser — so a missing grant
fails here rather than in production. That is the point of testing
against a role at all: `fact-writer` has INSERT on two tables and SELECT
on one, and nothing on `configured_facts`, `readings` or `divergences`,
because those are Phases 30 and 31 and their grant decisions must stay
visible rather than being pre-approved by a role that could already do
them.

The project-token tests are the ones worth reading twice. An unset
`CULPRIT_PROJECT_TOKEN` must *refuse*, not allow — the same fail-open
shape `app/env.py` exists to stamp out, and the one a shared bearer
credential invites, since an empty configured token trivially compares
equal to an empty presented one.
"""

import os
import pathlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from culprit_model.facts import Fact, Provenance
from culprit_model.planes import ConfidenceRank, Plane, SourceKind
from culprit_model.protocol import CaptureBundle
from culprit_model.shape import ValueShape
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
LEAKED = "postgresql://u:hunter2@db/orders"


def _fact(capture_id: uuid.UUID, subject: str, predicate: str, **extra: object) -> Fact:
    payload: dict[str, object] = {
        "plane": Plane.INTENT,
        "subject": subject,
        "predicate": predicate,
        "provenance": Provenance(
            source_kind=SourceKind.SPEC,
            extractor="culprit-extract-python@0.1.0",
            artefact="openapi.json",
            locator="$.paths./orders.post",
            confidence_rank=ConfidenceRank.COMMITTED_SPEC,
        ),
        "captured_at": datetime.now(UTC),
        "capture_id": capture_id,
    }
    payload.update(extra)
    return Fact(**payload)  # pyright: ignore[reportArgumentType]


def _bundle(**overrides: object) -> CaptureBundle:
    capture_id = uuid.uuid4()
    payload: dict[str, object] = {
        "extractor": "culprit@0.1.0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
        "facts": (
            _fact(
                capture_id,
                build("http", component="orders-api", method="POST", path="/api/v1/orders"),
                "exists",
                value={"path": "/api/v1/orders", "method": "POST"},
            ),
            _fact(
                capture_id,
                build("config", component="orders-api", key="DATABASE_URL"),
                "value_shape",
                value_shape=ValueShape.of(LEAKED),
            ),
        ),
        "meta": {"cli_version": "0.1.0"},
    }
    payload.update(overrides)
    return CaptureBundle(**payload)  # pyright: ignore[reportArgumentType]


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE captures CASCADE"))

    os.environ["FACT_WRITER_DATABASE_URL"] = role_database_url(
        "fact-writer", "FACT_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    # Deferred, like every other API test in this directory: these
    # modules read their DATABASE_URL at import time, and importing
    # before the container exists would bind to whatever was configured
    # first. `importlib.reload` because CULPRIT_PROJECT_TOKEN is read at
    # module scope too, and a previous test module may have imported it
    # already with a different value.
    import importlib

    from app.facts import config as facts_config
    from app.facts import dependencies as facts_dependencies

    importlib.reload(facts_config)
    importlib.reload(facts_dependencies)
    from app.facts import router as facts_router_module

    importlib.reload(facts_router_module)

    from app.errors import install as install_error_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(facts_config.FACT_WRITER_DATABASE_URL)
    app = FastAPI()
    app.state.fact_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # The same handler app/main.py installs — without it a 422 echoes the
    # rejected bundle, credentials and all, which is what this test app
    # needs to be able to assert.
    install_error_handlers(app)
    app.include_router(facts_router_module.router)

    with TestClient(app) as test_client:
        yield test_client
    await engine.dispose()


def _post(client: TestClient, bundle: CaptureBundle, token: str | None = PROJECT_TOKEN):
    """Posts the bundle exactly as the CLI would: its own JSON, verbatim.

    `content=`, not `json=`, deliberately — the wire format under test is
    what `CaptureBundle.model_dump_json()` produces, and re-encoding it
    through httpx's own serialiser would test httpx.
    """
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/facts/captures", content=bundle.model_dump_json(), headers=headers
    )


# --- authentication -----------------------------------------------------


def test_a_valid_project_token_is_accepted(client: TestClient) -> None:
    response = _post(client, _bundle())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["facts_stored"] == 2
    assert body["plane"] == "INTENT"


def test_no_token_is_refused(client: TestClient) -> None:
    assert _post(client, _bundle(), token=None).status_code == 401


def test_a_wrong_token_is_refused(client: TestClient) -> None:
    assert _post(client, _bundle(), token="not-the-token").status_code == 401


def test_an_unconfigured_token_refuses_everything(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed. An empty configured token would otherwise compare
    equal to an empty presented one and open the endpoint to anyone."""
    from app.facts import dependencies

    monkeypatch.setattr(dependencies, "CULPRIT_PROJECT_TOKEN", "")
    assert _post(client, _bundle()).status_code == 401
    assert _post(client, _bundle(), token="").status_code == 401


# --- what is stored -----------------------------------------------------


async def test_the_capture_and_its_facts_are_persisted(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    bundle = _bundle()
    assert _post(client, bundle).status_code == 201

    async with db_engine.begin() as conn:
        capture = (
            await conn.execute(
                text("SELECT plane, environment, extractor FROM captures WHERE id = :id"),
                {"id": bundle.capture_id},
            )
        ).one()
        assert capture.plane == "INTENT"
        # NULL exactly when the plane is INTENT — INTENT is
        # environment-independent by definition (§0.2), and a check
        # constraint in c07a5f31d8e4 enforces it.
        assert capture.environment is None
        assert capture.extractor == "culprit@0.1.0"

        rows = (
            await conn.execute(
                text(
                    "SELECT subject, predicate, confidence_rank, artefact, locator "
                    "FROM intent_facts WHERE capture_id = :id ORDER BY subject"
                ),
                {"id": bundle.capture_id},
            )
        ).all()
    assert len(rows) == 2
    assert rows[0].subject == build("config", component="orders-api", key="DATABASE_URL")
    assert rows[1].subject == build(
        "http", component="orders-api", method="POST", path="/api/v1/orders"
    )
    assert rows[1].confidence_rank == 80
    assert rows[1].artefact == "openapi.json"


async def test_no_config_value_reaches_the_database(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """The end-to-end form of acceptance criterion 3.

    The bundle carries a shape derived from a real DSN. What lands in
    `intent_facts` must not contain the DSN — checked by searching the
    stored rows, not by trusting the model that produced them.
    """
    bundle = _bundle()
    assert _post(client, bundle).status_code == 201
    async with db_engine.begin() as conn:
        blob = (
            await conn.execute(
                text(
                    "SELECT string_agg(value::text, ' ') FROM intent_facts "
                    "WHERE capture_id = :id"
                ),
                {"id": bundle.capture_id},
            )
        ).scalar_one()
    assert "hunter2" not in (blob or "")
    assert "postgresql://" not in (blob or "")


def test_a_bundle_carrying_an_ungranted_config_literal_is_rejected(
    client: TestClient,
) -> None:
    """Rejected by request validation, before any application code runs.

    The API deserialises `culprit_model.CaptureBundle` itself rather than
    a local copy of it, so `Fact`'s own validator is FastAPI's request
    validation. A hand-crafted payload that bypasses the CLI still cannot
    put a config value in this database.
    """
    capture_id = str(uuid.uuid4())
    payload = {
        "protocol": 1,
        "plane": "INTENT",
        "environment": None,
        "extractor": "hand-crafted@0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC).isoformat(),
        "facts": [
            {
                "plane": "INTENT",
                "subject": build("config", component="orders-api", key="DATABASE_URL"),
                "predicate": "value",
                "value": LEAKED,
                "provenance": {
                    "source_kind": "static",
                    "extractor": "hand-crafted@0",
                    "confidence_rank": 60,
                },
                "captured_at": datetime.now(UTC).isoformat(),
                "capture_id": capture_id,
            }
        ],
    }
    response = client.post(
        "/facts/captures",
        json=payload,
        headers={"Authorization": f"Bearer {PROJECT_TOKEN}"},
    )
    assert response.status_code == 422, response.text
    assert "grant_ref" in response.text


def test_a_configured_plane_bundle_is_refused_with_a_useful_message(
    client: TestClient,
) -> None:
    """Phases 30 and 31 own the other two planes, and `fact-writer` has
    no grant on their tables. Refused here, with a message naming the
    phase, rather than allowed through to fail as a Postgres permission
    error the caller cannot act on."""
    capture_id = uuid.uuid4()
    bundle = CaptureBundle(
        plane=Plane.CONFIGURED,
        environment="staging",
        extractor="culprit@0.1.0",
        capture_id=capture_id,
        started_at=datetime.now(UTC),
        facts=(),
    )
    response = _post(client, bundle)
    assert response.status_code == 422
    assert "Phase 30" in response.text


def test_a_fact_from_another_capture_is_refused(client: TestClient) -> None:
    """Refused rather than silently rewritten.

    `capture_id` is what makes a snapshot queryable as a snapshot. A fact
    carrying someone else's is either a client bug or two bundles spliced
    together, and quietly fixing it up would hide both.
    """
    bundle = _bundle()
    stray = _fact(
        uuid.uuid4(),
        build("http", component="orders-api", method="GET", path="/healthz"),
        "exists",
        value=True,
    )
    spliced = bundle.model_copy(update={"facts": (*bundle.facts, stray)})
    response = _post(client, spliced)
    assert response.status_code == 422
    assert "capture_id" in response.text


async def test_an_empty_bundle_is_accepted_and_recorded(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """A capture that found nothing is still a capture.

    Dropping it would make "we looked and found nothing" and "we never
    looked" indistinguishable, which is exactly the distinction the
    `skipped` list exists to preserve.
    """
    bundle = _bundle(facts=())
    response = _post(client, bundle)
    assert response.status_code == 201
    assert response.json()["facts_stored"] == 0
    async with db_engine.begin() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM captures WHERE id = :id"),
                {"id": bundle.capture_id},
            )
        ).scalar_one()
    assert count == 1


def test_skips_are_echoed_back(client: TestClient) -> None:
    """"Stored 214 facts, skipped client_calls because the extractor is
    not installed" is the line that gets an extractor installed."""
    from culprit_model.protocol import Skip

    bundle = _bundle(
        skipped=(
            Skip(want="client_calls", reason="culprit-extract-node is not installed"),
        )
    )
    response = _post(client, bundle)
    assert response.status_code == 201
    assert response.json()["skipped"] == 1


# --- the role -----------------------------------------------------------


async def test_fact_writer_cannot_touch_the_other_planes_tables(
    migrated_database_url: str, role_database_url
) -> None:
    """Least privilege, asserted rather than assumed.

    `fact-writer` exists so an unattended CI credential cannot do
    anything but post an INTENT capture. If a later phase widens it
    instead of adding a role (.claude/rules/database.md), this fails.
    """
    from sqlalchemy import text as sql
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        role_database_url("fact-writer", "FACT_WRITER_DB_PASSWORD")
    )
    try:
        for table in ("configured_facts", "readings", "divergences"):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(sql(f"SELECT 1 FROM {table} LIMIT 1"))
        # And it cannot delete what it wrote, either.
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with engine.begin() as conn:
                await conn.execute(sql("DELETE FROM intent_facts"))
    finally:
        await engine.dispose()


# --- the plane and shape defects the Phase 28 invariant audit found ----


def test_a_configured_fact_inside_an_intent_bundle_is_refused(
    client: TestClient,
) -> None:
    """The audit's V2, verbatim.

    A bundle declaring INTENT whose fact says CONFIGURED used to be
    accepted. `intent_facts` has no `plane` and no `environment` column —
    the plane *is* the table — so a reading of production landed as a
    claim about what the system is supposed to do, with its environment
    and its grant silently discarded, and a live DSN sitting in a table
    with no grant column at all.

    Refused by request validation now, so no code path can route around
    it.
    """
    capture_id = str(uuid.uuid4())
    payload = {
        "protocol": 1,
        "plane": "INTENT",
        "environment": None,
        "extractor": "hand-crafted@0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC).isoformat(),
        "facts": [
            {
                "plane": "CONFIGURED",
                "environment": "production",
                "subject": build("config", component="orders-api", key="DATABASE_URL"),
                "predicate": "value",
                "value": LEAKED,
                "grant_ref": "grant:config.read.values/DATABASE_URL",
                "provenance": {
                    "source_kind": "introspection",
                    "extractor": "hand-crafted@0",
                    "confidence_rank": 90,
                },
                "captured_at": datetime.now(UTC).isoformat(),
                "capture_id": capture_id,
            }
        ],
    }
    response = client.post(
        "/facts/captures", json=payload, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 422, response.text
    assert "plane" in response.text
    assert "hunter2" not in response.text


def test_a_fact_from_another_environment_is_refused(client: TestClient) -> None:
    """A bundle for staging carrying a fact stamped production is two
    captures spliced together, and storing either answer is a guess."""
    capture_id = str(uuid.uuid4())
    payload = {
        "protocol": 1,
        "plane": "CONFIGURED",
        "environment": "staging",
        "extractor": "hand-crafted@0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC).isoformat(),
        "facts": [
            {
                "plane": "CONFIGURED",
                "environment": "production",
                "subject": build("config", component="orders-api", key="PORT"),
                "predicate": "value_shape",
                "value_shape": {
                    "type": "string",
                    "length_class": "short",
                    "format": "port",
                    "present": True,
                },
                "provenance": {
                    "source_kind": "introspection",
                    "extractor": "hand-crafted@0",
                    "confidence_rank": 90,
                },
                "captured_at": datetime.now(UTC).isoformat(),
                "capture_id": capture_id,
            }
        ],
    }
    response = client.post(
        "/facts/captures", json=payload, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 422, response.text
    assert "environment" in response.text


async def test_a_value_shape_survives_the_round_trip(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """The audit's V3.

    Half the config facts an INTENT capture produces are shape-only —
    `predicate: value_shape`, no `value` at all. They used to be accepted,
    written with `value = NULL`, and the shape discarded, while the
    response reported them stored. Asserted against the stored row, not
    the response.
    """
    bundle = _bundle()
    assert _post(client, bundle).status_code == 201

    async with db_engine.begin() as conn:
        shape = (
            await conn.execute(
                text(
                    "SELECT value_shape FROM intent_facts "
                    "WHERE capture_id = :id AND predicate = 'value_shape'"
                ),
                {"id": bundle.capture_id},
            )
        ).scalar_one()
    assert shape is not None, "the value_shape was dropped on the way in"
    assert shape == {
        "type": "string",
        "length_class": "medium",
        "format": "dsn",
        "present": True,
    }


async def test_intent_facts_refuses_an_ungranted_config_literal_at_the_db(
    db_engine: AsyncEngine,
) -> None:
    """Defence in depth, on the table that is actually writable.

    The Phase 26.1 guarantee protected `configured_facts`, which nothing
    writes yet. `intent_facts` is the one an unattended CI credential can
    now INSERT into, so it carries the same constraint — asserted by
    making the database refuse a row, not by reading the migration.
    """
    from sqlalchemy.exc import IntegrityError

    capture_id = uuid.uuid4()
    async def insert(**columns: object) -> None:
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO captures (id, plane, extractor, started_at) "
                    "VALUES (:cid, 'INTENT', 't@1', now())"
                ),
                {"cid": columns["cid"]},
            )
            await conn.execute(
                text(
                    "INSERT INTO intent_facts (capture_id, subject, predicate, value, "
                    "value_shape, grant_ref, source_kind, extractor, confidence_rank, "
                    "captured_at) VALUES (:cid, :subject, 'value', CAST(:value AS jsonb), "
                    "CAST(:shape AS jsonb), :grant, 'static', 't@1', 60, now())"
                ),
                columns,
            )

    subject = build("config", component="orders-api", key="DATABASE_URL")
    with pytest.raises(IntegrityError, match="ck_intent_facts_value_requires_grant"):
        await insert(cid=capture_id, subject=subject, value=f'"{LEAKED}"', shape=None, grant=None)

    # A shape that is not the closed four-field form is refused too.
    with pytest.raises(IntegrityError, match="ck_intent_facts_value_shape_is_closed"):
        await insert(
            cid=uuid.uuid4(),
            subject=subject,
            value="null",
            shape=f'{{"type": "url", "sample": "{LEAKED}"}}',
            grant=None,
        )

    # And the ordinary shape-only fact still goes in.
    await insert(
        cid=uuid.uuid4(),
        subject=subject,
        value="null",
        shape='{"type": "string", "length_class": "medium", "format": "dsn", "present": true}',
        grant=None,
    )


def test_a_422_does_not_echo_the_rejected_body(client: TestClient) -> None:
    """A refusal must not write the credential into two log stores.

    FastAPI's default validation handler puts the offending value in the
    response, from where it reaches this API's access log and the CI log
    of whatever posted it. The caller already had the value, so nothing
    is disclosed to a third party — but it would be strange to hold
    extractors to "never carry a config value" while the error path
    quietly published one. See app/errors.py.
    """
    capture_id = str(uuid.uuid4())
    payload = {
        "protocol": 1,
        "plane": "INTENT",
        "environment": None,
        "extractor": "hand-crafted@0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC).isoformat(),
        "facts": [
            {
                "plane": "INTENT",
                "subject": build("config", component="orders-api", key="DATABASE_URL"),
                "predicate": "value",
                "value": LEAKED,
                "provenance": {
                    "source_kind": "static",
                    "extractor": "hand-crafted@0",
                    "confidence_rank": 60,
                },
                "captured_at": datetime.now(UTC).isoformat(),
                "capture_id": capture_id,
            }
        ],
    }
    response = client.post(
        "/facts/captures", json=payload, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 422
    body = response.text
    assert "hunter2" not in body, "the rejected value was echoed back"
    assert "postgresql://" not in body
    # Still useful: the caller is told which field and why.
    assert "facts" in body
    assert "grant_ref" in body


def test_reposting_the_same_capture_is_a_409_not_a_500(client: TestClient) -> None:
    """A retry is a normal event, not a server fault.

    `capture_id` is derived by the client from the capture's own content
    and time, so a re-run of a CI step that already succeeded posts the
    same id. That used to reach Postgres as a primary-key violation and
    surface as a 500 with a traceback in the log.
    """
    bundle = _bundle()
    assert _post(client, bundle).status_code == 201
    again = _post(client, bundle)
    assert again.status_code == 409, again.text
    assert str(bundle.capture_id) in again.text


@pytest.mark.parametrize(
    "golden",
    sorted(
        (
            pathlib.Path(__file__).resolve().parents[2]
            / "cli"
            / "testdata"
            / "fixtures"
            / "golden"
        ).rglob("*.json")
    ),
    ids=lambda p: p.stem,
)
async def test_a_real_capture_from_the_cli_is_accepted(
    client: TestClient, db_engine: AsyncEngine, golden: pathlib.Path
) -> None:
    """The whole pipeline, end to end, with nothing hand-built.

    These files are real `culprit intent` output over the fixture corpus,
    written by the Go binary. Posting them here is the only test that
    exercises the actual contract — Go marshals, FastAPI validates
    against the pydantic model, the `fact-writer` role inserts — rather
    than a Python-shaped approximation of it.

    It has already caught one defect that nothing else would have: Go's
    nil slice marshals to `null`, so a capture that found nothing (the
    honest "no extractor installed" outcome) was rejected 422 by the one
    endpoint that exists to receive it.
    """
    raw = golden.read_text(encoding="utf-8")
    bundle = CaptureBundle.model_validate_json(raw)

    response = client.post(
        "/facts/captures",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {PROJECT_TOKEN}",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["facts_stored"] == len(bundle.facts)

    async with db_engine.begin() as conn:
        stored, shapes = (
            await conn.execute(
                text(
                    "SELECT count(*), count(value_shape) FROM intent_facts "
                    "WHERE capture_id = :id"
                ),
                {"id": bundle.capture_id},
            )
        ).one()
    assert stored == len(bundle.facts)
    # And the shapes survived, which is the half that used to be dropped.
    expected_shapes = sum(1 for fact in bundle.facts if fact.value_shape is not None)
    assert shapes == expected_shapes


# --- the four violations the re-audit found (V4-V7) --------------------


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param("CONFIG:orders-api/DATABASE_URL", id="upper-cased scheme"),
        pytest.param(" config:orders-api/DATABASE_URL", id="leading space"),
        # Derived from a real subject rather than written out: a
        # hand-formatted one would trip the subject-construction lint,
        # and deriving it says what the case actually is — a valid
        # config subject with its key cut off, which still matches the
        # database's scheme test while failing to parse.
        pytest.param(
            build("config", component="orders-api", key="DATABASE_URL").split("/")[0],
            id="parses-fail but LIKE-matches",
        ),
        pytest.param("opaque:postgresql://u:hunter2@db/orders", id="unknown scheme"),
    ],
)
async def test_a_non_canonical_subject_cannot_smuggle_a_config_value(
    client: TestClient, db_engine: AsyncEngine, subject: str
) -> None:
    """V4, the one that mattered most.

    `Fact` used to return early when a subject did not parse — "that is
    `build()`'s error to raise" — but nothing on this path ever calls
    `build()`: the wire carries a string and extractors are third-party
    subprocesses. The database's own check keys off an anchored,
    case-sensitive LIKE on the scheme, so it skipped these too. Both
    layers opened at once, and the audit stored a live DSN through both.
    """
    capture_id = str(uuid.uuid4())
    payload = {
        "protocol": 1,
        "plane": "INTENT",
        "environment": None,
        "extractor": "hand-crafted@0",
        "capture_id": capture_id,
        "started_at": datetime.now(UTC).isoformat(),
        "facts": [
            {
                "plane": "INTENT",
                "subject": subject,
                "predicate": "value",
                "value": LEAKED,
                "provenance": {
                    "source_kind": "static",
                    "extractor": "hand-crafted@0",
                    "confidence_rank": 60,
                },
                "captured_at": datetime.now(UTC).isoformat(),
                "capture_id": capture_id,
            }
        ],
    }
    response = client.post(
        "/facts/captures", json=payload, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 422, response.text
    assert "hunter2" not in response.text

    async with db_engine.begin() as conn:
        stored = (
            await conn.execute(
                text("SELECT count(*) FROM intent_facts WHERE value::text LIKE :like"),
                {"like": "%hunter2%"},
            )
        ).scalar_one()
    assert stored == 0, "an ungranted config literal reached the database"


async def test_a_database_refusal_is_a_422_that_does_not_echo_the_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V5. A CHECK violation used to escape as a 500.

    Postgres's error text for a CHECK violation carries
    `DETAIL: Failing row contains (...)` — for a config fact, that is the
    value the constraint was refusing. Starlette then wrote the whole
    traceback into the log. Simulated by disabling the model-level guard
    so the database is the layer that refuses, which is exactly the
    "a future writer bypasses the model" case the constraint exists for.
    """
    from app.facts import service

    async def _no_op(*_args: object, **_kwargs: object) -> None:
        return None

    # Let a bad row reach the insert: bypass the in-Python guard only.
    monkeypatch.setattr(service, "_intent_row", _bad_intent_row)

    bundle = _bundle()
    response = _post(client, bundle)
    assert response.status_code == 422, response.text
    assert "hunter2" not in response.text
    assert "Failing row" not in response.text
    assert "grant_ref" in response.text


def _bad_intent_row(fact: object, bundle: object) -> dict[str, object]:
    """An `intent_facts` row the database must refuse: a config subject
    carrying a literal with no grant."""
    return {
        "id": uuid.uuid4(),
        "capture_id": bundle.capture_id,  # type: ignore[attr-defined]
        "subject": build("config", component="orders-api", key="DATABASE_URL"),
        "predicate": "value",
        "value": LEAKED,
        "value_shape": None,
        "grant_ref": None,
        "source_kind": "static",
        "extractor": "t@1",
        "artefact": None,
        "locator": None,
        "confidence_rank": 60,
        "captured_at": datetime.now(UTC),
    }


def test_a_mismatched_capture_id_names_the_index_not_the_subject(
    client: TestClient,
) -> None:
    """R4. The subject is attacker-controlled text, and the error used to
    echo it into the 422 body and the access log — a subject being
    exactly where somebody would hide a value."""
    bundle = _bundle()
    stray = _fact(
        uuid.uuid4(),
        build("http", component="orders-api", method="GET", path="/healthz"),
        "exists",
        value=True,
    )
    response = _post(client, bundle.model_copy(update={"facts": (*bundle.facts, stray)}))
    assert response.status_code == 422
    assert "facts.2" in response.text
    assert "healthz" not in response.text
