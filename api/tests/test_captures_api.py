"""`/captures` (Phase 30 field 9), against a real database, under the real
roles: `capture-writer` for `POST`, `api-reader` for the two `GET`s.

The planted value is the thing to follow. The conformance envelope Go
sealed carries a *granted* literal — `LOG_LEVEL=debug`, on the capture's
`config.read.values` allowlist — so it is stored in `configured_facts.value`
exactly as the grant permits. `api-reader` can read that column. No
response may ever contain it: `fact_out` is the one serialiser, and these
tests assert on the raw response text rather than on a parsed field, so a
value that leaked through any field at all would be caught.
"""

import base64
import hashlib
import importlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
# Built, never hand-formatted — scripts/tests/test_subject_construction.py
# holds tests to the same rule as application code.
LOG_LEVEL = build("config", component="orders-api", key="LOG_LEVEL")
DATABASE_URL = build("config", component="orders-api", key="DATABASE_URL")
IMAGE = build("image", component="orders-api")
ORDERS_TABLE = build("schema", database="orders-api-db", namespace="public", table="orders")
FIXTURE = Path(__file__).parents[2] / "shared" / "tests" / "capture_envelope_conformance.json"
GRANTED_VALUE = "debug"


def _envelope() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _reseal(envelope: dict, mutate) -> dict:
    """A second capture built from the first: a new environment and
    capture id, unsigned, with its digest recomputed — the way `culprit
    env capture` without --sign-key would have written it."""
    raw = json.loads(base64.b64decode(envelope["payload"]))
    mutate(raw)
    for fact in raw["facts"]:
        fact["capture_id"] = raw["capture_id"]
        fact["environment"] = raw["environment"]
    payload = json.dumps(raw).encode()
    return {
        "payload_type": envelope["payload_type"],
        "payload": base64.b64encode(payload).decode(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "signatures": [],
    }


def _production(raw: dict) -> None:
    raw["environment"] = "production"
    raw["capture_id"] = str(uuid.uuid4())
    # DATABASE_URL unset, a different granted LOG_LEVEL, a different digest.
    raw["facts"] = [f for f in raw["facts"] if f["subject"] != DATABASE_URL]
    for fact in raw["facts"]:
        if fact["predicate"] == "value":
            fact["value"] = "info"
        if fact["predicate"] == "digest":
            fact["value"] = "sha256:" + "2" * 64


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE captures CASCADE"))

    os.environ["CAPTURE_WRITER_DATABASE_URL"] = role_database_url(
        "capture-writer", "CAPTURE_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    from app.facts import dependencies as facts_dependencies
    from app.model import capture_config

    importlib.reload(capture_config)
    importlib.reload(facts_dependencies)
    from app.model import captures_router as captures_router_module

    importlib.reload(captures_router_module)

    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    writer = create_async_engine(capture_config.CAPTURE_WRITER_DATABASE_URL)
    reader = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    app = FastAPI()
    app.state.capture_session_factory = async_sessionmaker(writer, expire_on_commit=False)
    app.state.session_factory = async_sessionmaker(reader, expire_on_commit=False)
    install_error_handlers(app)
    app.include_router(captures_router_module.router)
    # A user session is require_auth's own concern and has its own tests;
    # here it only has to be *present* on the GETs.
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}

    with TestClient(app) as test_client:
        yield test_client
    await writer.dispose()
    await reader.dispose()


def _post(client: TestClient, envelope: dict, token: str | None = PROJECT_TOKEN):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/captures", content=json.dumps(envelope), headers=headers)


def test_a_signed_capture_is_verified_and_stored(client: TestClient) -> None:
    response = _post(client, _envelope())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["environment"] == "staging"
    assert body["facts_stored"] == 5
    assert body["refused"] == 1
    assert body["signed_by"] is not None
    assert body["digest"] == _envelope()["sha256"]


@pytest.mark.asyncio
async def test_the_granted_value_is_stored_and_never_returned(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    capture_id = _post(client, _envelope()).json()["capture_id"]

    # Stored, under its grant — which is what the grant is for.
    async with db_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT value, grant_ref FROM configured_facts WHERE subject = :subject"),
                {"subject": LOG_LEVEL},
            )
        ).one()
    assert row.value == GRANTED_VALUE
    assert row.grant_ref == "config.read.values:orders-api/LOG_LEVEL"

    # Never returned.
    response = client.get(f"/captures/{capture_id}")
    assert response.status_code == 200, response.text
    assert f'"{GRANTED_VALUE}"' not in response.text
    facts = {(f["subject"], f["predicate"]): f for f in response.json()["facts"]}
    assert facts[(LOG_LEVEL, "value")]["value"] == "(a value, not shown)"
    assert facts[(DATABASE_URL, "value_shape")]["value"] == "string/dsn(postgresql)/medium"
    # A capture read back still says what it did not look at.
    assert response.json()["refused"][0]["capability"] == "net.dns.resolve"
    assert {g["capability"] for g in response.json()["grants"]} >= {"config.read.values"}


def test_the_diff_says_what_differs_and_never_what_it_differs_to(client: TestClient) -> None:
    staging = _post(client, _envelope()).json()["capture_id"]
    production = _post(client, _reseal(_envelope(), _production)).json()["capture_id"]

    response = client.get("/captures/diff", params={"a": staging, "b": production})
    assert response.status_code == 200, response.text
    for value in (GRANTED_VALUE, "info", "hunter2"):
        assert f'"{value}"' not in response.text
    entries = {(e["subject"], e["predicate"]): e for e in response.json()["entries"]}
    assert entries[(DATABASE_URL, "exists")]["status"] == "only_in_a"
    assert entries[(LOG_LEVEL, "value")]["status"] == "differs"
    assert entries[(IMAGE, "digest")]["status"] == "differs"
    assert (ORDERS_TABLE, "columns") not in entries


def test_a_duplicate_is_a_409(client: TestClient) -> None:
    assert _post(client, _envelope()).status_code == 201
    assert _post(client, _envelope()).status_code == 409


def test_an_altered_capture_is_a_422_that_quotes_nothing(client: TestClient) -> None:
    envelope = _envelope()
    envelope["sha256"] = "0" + envelope["sha256"][1:]
    response = _post(client, envelope)
    assert response.status_code == 422
    assert envelope["payload"][:40] not in response.text


def test_an_ungranted_value_is_a_422(client: TestClient) -> None:
    def ungrant(raw: dict) -> None:
        raw["capture_id"] = str(uuid.uuid4())
        raw["grants"] = [g for g in raw["grants"] if g["capability"] != "config.read.values"]

    response = _post(client, _reseal(_envelope(), ungrant))
    assert response.status_code == 422
    assert "does not list" in response.text
    assert GRANTED_VALUE not in response.text


def test_no_project_token_is_a_401(client: TestClient) -> None:
    assert _post(client, _envelope(), token=None).status_code == 401
    assert _post(client, _envelope(), token="wrong").status_code == 401


def test_an_intent_capture_id_is_not_readable_here(client: TestClient) -> None:
    assert client.get(f"/captures/{uuid.uuid4()}").status_code == 404


@pytest.mark.asyncio
async def test_capture_writer_can_do_exactly_what_the_endpoint_needs(role_database_url) -> None:
    """A new role, not a third reuse of fact-writer (.claude/rules/database.md).
    Asserted both ways: what it can do, and — the half that matters if a
    project token leaks — everything else it cannot."""
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(role_database_url("capture-writer", "CAPTURE_WRITER_DB_PASSWORD"))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM captures LIMIT 1"))
        # INSERT on configured_facts, but it cannot read the table back:
        # a leaked credential appends to history, it does not browse it.
        for statement in (
            "SELECT 1 FROM configured_facts LIMIT 1",
            "SELECT 1 FROM intent_facts LIMIT 1",
            "SELECT 1 FROM divergences LIMIT 1",
            "SELECT 1 FROM readings LIMIT 1",
            "SELECT 1 FROM users LIMIT 1",
            "SELECT 1 FROM api_keys LIMIT 1",
            "SELECT 1 FROM components LIMIT 1",
            "DELETE FROM captures",
            "UPDATE captures SET environment = 'rewritten'",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_reader_reads_captures_and_writes_nothing(role_database_url) -> None:
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM captures LIMIT 1"))
            await conn.execute(text("SELECT 1 FROM configured_facts LIMIT 1"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM configured_facts"))
    finally:
        await engine.dispose()
