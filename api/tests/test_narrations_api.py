"""Narrations in the control plane (Phase 35 part 2), against a real
database under the real roles: `narrator` writes, `api-reader` reads, and
the API runs the narration check again before it serves prose.

What this holds: the narrator can append and nothing else — it cannot
update, delete or truncate a narration (and neither can the owner), nor
write an investigation; a fourth attempt cannot be committed; each status
carries only its own columns; and a row put into the table by any route
other than the narrator's check is not served as prose.
"""

import importlib
import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from culprit_model.investigations import Investigation
from culprit_model.narration import evidence
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
#: A component the recorded investigation does not hold.
BILLING = build("component", name="billing-service")
RECORDED = Path(__file__).parent / "data" / "investigations"
INSERT = text(
    "INSERT INTO narrations (id, investigation_id, attempt, status, provider, model, prose, "
    "reason, named) VALUES (:id, :inv, :attempt, :status, 'ollama', 'stub', :prose, :reason, "
    ":named)"
)


def recorded(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / f"{name}.json").read_text("utf-8"))


@pytest.fixture
def provider() -> Iterator[None]:
    """LLM_PROVIDER as each test sets it; `none` unless it says otherwise."""
    before = os.environ.get("LLM_PROVIDER")
    yield
    if before is None:
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = before


def _app(role_database_url) -> FastAPI:
    from app.narrations import config, service
    from app.narrations import router as narrations_router

    for module in (config, service, narrations_router):
        importlib.reload(module)
    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers
    from app.investigations import router as investigations_router

    importlib.reload(investigations_router)
    app = FastAPI()
    app.state.investigation_writer_session_factory = async_sessionmaker(
        create_async_engine(
            role_database_url("investigation-writer", "INVESTIGATION_WRITER_DB_PASSWORD")
        ),
        expire_on_commit=False,
    )
    app.state.session_factory = async_sessionmaker(
        create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD")),
        expire_on_commit=False,
    )
    install_error_handlers(app)
    app.include_router(investigations_router.router)
    app.include_router(narrations_router.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}
    return app


@pytest_asyncio.fixture
async def narrator(
    migrated_database_url: str, role_database_url, db_engine: AsyncEngine
) -> AsyncIterator[AsyncEngine]:
    async with db_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE narrations DISABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE verifications DISABLE TRIGGER USER"))
        await conn.execute(text("TRUNCATE investigations, narrations, verifications CASCADE"))
        await conn.execute(text("ALTER TABLE verifications ENABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations ENABLE TRIGGER USER"))
    os.environ["INVESTIGATION_WRITER_DATABASE_URL"] = role_database_url(
        "investigation-writer", "INVESTIGATION_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN
    from app.agents import dependencies as agents_dependencies
    from app.facts import dependencies as facts_dependencies

    importlib.reload(facts_dependencies)
    importlib.reload(agents_dependencies)
    engine = create_async_engine(role_database_url("narrator", "NARRATOR_DB_PASSWORD"))
    yield engine
    await engine.dispose()


def client_for(role_database_url, llm_provider: str = "none") -> TestClient:
    os.environ["LLM_PROVIDER"] = llm_provider
    return TestClient(_app(role_database_url))


def store(client: TestClient, name: str = "auth-audience") -> dict[str, Any]:
    investigation = recorded(name)
    response = client.post(
        "/investigations", json=investigation, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 201, response.text
    return investigation


async def insert(engine: AsyncEngine, inv: str, attempt: int, status: str, **columns) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            INSERT,
            {
                "id": f"nar-{attempt:016x}",
                "inv": inv,
                "attempt": attempt,
                "status": status,
                "prose": columns.get("prose"),
                "reason": columns.get("reason"),
                "named": columns.get("named"),
            },
        )


def narration(client: TestClient, investigation: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"/investigations/{investigation['id']}/narration")
    assert response.status_code == 200, response.text
    return response.json()


# ---- what is served --------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_and_not_narrated_yet_are_said_and_never_pending(
    narrator: AsyncEngine, role_database_url, provider
) -> None:
    with client_for(role_database_url, "none") as client:
        investigation = store(client)
        assert narration(client, investigation)["state"] == "off"
    with client_for(role_database_url, "ollama") as client:
        shown = narration(client, investigation)
        assert shown["state"] == "not_narrated" and shown["attempts"] == 0
        assert client.get("/investigations/inv-0000000000000000/narration").status_code == 404


@pytest.mark.asyncio
async def test_a_complete_narration_is_served_with_each_citation_as_the_records_text(
    narrator: AsyncEngine, role_database_url, provider
) -> None:
    with client_for(role_database_url, "ollama") as client:
        investigation = store(client)
        prose = "The token carries the wrong audience [2]. **Change** it as recommended [3]."
        await insert(narrator, investigation["id"], 1, "complete", prose=prose)

        shown = narration(client, investigation)

    assert shown["state"] == "complete"
    assert (shown["provider"], shown["model"], shown["attempts"]) == ("ollama", "stub", 1)
    items = {i.number: i.text for i in evidence(Investigation.model_validate(investigation))}
    assert shown["segments"] == [
        {"text": "The token carries the wrong audience ", "evidence": None},
        {"text": items[2], "evidence": 2},
        {"text": ". **Change** it as recommended ", "evidence": None},
        {"text": items[3], "evidence": 3},
        {"text": ".", "evidence": None},
    ]


@pytest.mark.asyncio
async def test_failed_and_refused_are_served_with_their_reason_and_what_was_named(
    narrator: AsyncEngine, role_database_url, provider
) -> None:
    with client_for(role_database_url, "ollama") as client:
        investigation = store(client)
        await insert(narrator, investigation["id"], 1, "failed", reason="ollama answered HTTP 500")
        failed = narration(client, investigation)
        await insert(narrator, investigation["id"], 2, "refused", named=["billing-service"])
        refused = narration(client, investigation)

    assert (failed["state"], failed["reason"], failed["segments"]) == (
        "failed",
        "ollama answered HTTP 500",
        None,
    )
    assert (refused["state"], refused["named"], refused["attempts"]) == (
        "refused",
        ["billing-service"],
        2,
    )
    assert refused["segments"] is None


@pytest.mark.asyncio
async def test_a_row_inserted_with_unchecked_prose_is_not_served_as_prose(
    narrator: AsyncEngine, db_engine: AsyncEngine, role_database_url, provider
) -> None:
    """The owner can insert anything a CHECK allows. The API checks again."""
    with client_for(role_database_url, "ollama") as client:
        investigation = store(client)
        await insert(
            db_engine,
            investigation["id"],
            1,
            "complete",
            prose=f"Blame {BILLING} [99], see https://evil.example/x",
        )
        shown = narration(client, investigation)

    assert shown["state"] == "refused"
    assert shown["segments"] is None
    assert shown["named"] == ["[99]", "a URL", BILLING]


# ---- what the database holds ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_narrator_can_append_and_nothing_else(
    narrator: AsyncEngine, db_engine: AsyncEngine, role_database_url, provider
) -> None:
    with client_for(role_database_url) as client:
        investigation = store(client)
    await insert(narrator, investigation["id"], 1, "failed", reason="ollama answered HTTP 500")

    # It reads what it narrates, and its own narrations.
    async with narrator.connect() as conn:
        for table in ("investigations", "investigation_readings", "narrations"):
            await conn.execute(text(f"SELECT * FROM {table}"))

    refused_to_the_narrator = (
        "UPDATE narrations SET reason = 'changed'",
        "DELETE FROM narrations",
        "TRUNCATE narrations",
        "INSERT INTO investigations (id, opened_at, environment, symptom, ingested_at, "
        "submitted_by) VALUES ('inv-x', now(), 'e', '{}', now(), 'project-token')",
        "SELECT * FROM verifications",
        "SELECT * FROM readings",
    )
    for statement in refused_to_the_narrator:
        with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
            async with narrator.begin() as conn:
                await conn.execute(text(statement))

    # And the owner is refused an update, a delete or a truncate as well.
    for statement in (
        "UPDATE narrations SET reason = 'changed'",
        "DELETE FROM narrations",
        "TRUNCATE narrations",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_engine.begin() as conn:
                await conn.execute(text(statement))


@pytest.mark.asyncio
async def test_a_fourth_attempt_and_a_status_carrying_another_s_columns_are_refused(
    narrator: AsyncEngine, role_database_url, provider
) -> None:
    with client_for(role_database_url) as client:
        investigation = store(client)
    inv = investigation["id"]
    for status, columns in (
        ("complete", {}),
        ("complete", {"prose": "p [1]", "reason": "r"}),
        ("failed", {"prose": "p"}),
        ("refused", {"named": []}),
        ("pending", {"reason": "r"}),
    ):
        with pytest.raises(DBAPIError, match="ck_narrations_status_carries_its_own"):
            await insert(narrator, inv, 1, status, **columns)

    for attempt in (1, 2, 3):
        await insert(narrator, inv, attempt, "failed", reason="ollama answered HTTP 500")
    with pytest.raises(DBAPIError, match="ck_narrations_three_attempts"):
        await insert(narrator, inv, 4, "failed", reason="ollama answered HTTP 500")


@pytest.mark.asyncio
async def test_api_reader_reads_narrations_and_writes_none(
    narrator: AsyncEngine, role_database_url, provider
) -> None:
    reader = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    try:
        async with reader.connect() as conn:
            await conn.execute(text("SELECT * FROM narrations"))
        with pytest.raises(DBAPIError, match="permission denied"):
            async with reader.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO narrations (id, investigation_id, attempt, status, "
                        "provider, model, reason) VALUES ('nar-00000000000000aa', 'inv-x', 1, "
                        "'failed', 'ollama', 'm', 'r')"
                    )
                )
    finally:
        await reader.dispose()
