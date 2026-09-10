"""`POST /divergences/captures` (Phase 29 field 9), against a real database.

Driven under the real `fact-writer` role, like the facts endpoint, so a
missing grant fails here rather than in production.

The tests worth reading twice are the history ones. The endpoint exists
because a team wants to know what is new and what has been broken since
Tuesday, and an implementation that appends a row per CI run answers
neither question while looking, from the outside, like it works.
"""

import importlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from culprit_model.facts import (
    Divergence,
    DivergenceKind,
    Fact,
    Provenance,
    Severity,
)
from culprit_model.planes import ConfidenceRank, Plane, SourceKind
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
LEAKED = "postgresql://u:hunter2@db/orders"

ROUTE = build("http", component="orders-api", method="GET", path="/orders/{}/refunds")

#: A fixed capture id, so two runs of the same fixture produce the same
#: facts and the history assertions are about the endpoint rather than
#: about a uuid4 that changed underneath them.
CAPTURE = uuid.UUID("00000000-0000-4000-8000-00000000c0de")


def _fact(extractor: str, artefact: str, rank: int, **extra: object) -> Fact:
    payload: dict[str, object] = {
        "plane": Plane.INTENT,
        "subject": ROUTE,
        "predicate": "exists",
        "value": True,
        "provenance": Provenance(
            source_kind=SourceKind.STATIC,
            extractor=extractor,
            artefact=artefact,
            confidence_rank=rank,
        ),
        "captured_at": datetime.now(UTC),
        "capture_id": CAPTURE,
    }
    payload.update(extra)
    return Fact(**payload)  # pyright: ignore[reportArgumentType]


def _divergence(**overrides: object) -> Divergence:
    payload: dict[str, object] = {
        "kind": DivergenceKind.INTENT_CONFLICT,
        "subject": ROUTE,
        "predicate": "exists",
        "left": _fact(
            "culprit-extract-node@0.1.0",
            "frontend/src/lib/api.ts",
            ConfidenceRank.STATIC_CLIENT_CALL_SITES,
        ),
        "right": _fact(
            "culprit-extract-python@0.1.0",
            "api/app/main.py",
            ConfidenceRank.RUNTIME_INTROSPECTION,
            value=False,
        ),
        "severity": Severity.BREAKS_REQUEST_PATH,
        "explanation": "the dashboard calls a route the API does not serve",
        "severity_reason": "orders-api is on the request path from web",
    }
    payload.update(overrides)
    return Divergence(**payload)  # pyright: ignore[reportArgumentType]


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE divergences CASCADE"))
        await conn.execute(text("TRUNCATE captures CASCADE"))

    os.environ["FACT_WRITER_DATABASE_URL"] = role_database_url(
        "fact-writer", "FACT_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    from app.divergences import config as divergences_config
    from app.facts import config as facts_config
    from app.facts import dependencies as facts_dependencies

    importlib.reload(facts_config)
    importlib.reload(facts_dependencies)
    importlib.reload(divergences_config)
    from app.divergences import router as divergences_router_module

    importlib.reload(divergences_router_module)

    from app.errors import install as install_error_handlers

    engine = create_async_engine(divergences_config.DIVERGENCE_WRITER_DATABASE_URL)
    app = FastAPI()
    app.state.divergence_session_factory = async_sessionmaker(
        engine, expire_on_commit=False
    )
    install_error_handlers(app)
    app.include_router(divergences_router_module.router)

    with TestClient(app) as test_client:
        yield test_client
    await engine.dispose()


def _post(client: TestClient, payload: dict, token: str | None = PROJECT_TOKEN):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/divergences/captures", json=payload, headers=headers)


def _body(*divergences: Divergence, capture_id: uuid.UUID | None = None) -> dict:
    payload: dict = {
        "divergences": [
            divergence.model_dump(mode="json") for divergence in divergences
        ]
    }
    if capture_id is not None:
        payload["capture_id"] = str(capture_id)
    return payload


# --- authentication -----------------------------------------------------


def test_a_project_token_is_required(client: TestClient) -> None:
    assert _post(client, _body(_divergence()), token=None).status_code == 401
    assert _post(client, _body(_divergence()), token="wrong").status_code == 401


def test_a_valid_token_is_accepted(client: TestClient) -> None:
    response = _post(client, _body(_divergence()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["first_seen"] == 1
    assert body["seen_again"] == 0


# --- history, which is the entire reason this endpoint exists -----------


def test_the_same_finding_twice_is_one_row(client: TestClient) -> None:
    """A CI job runs on every push. An unfixed fault must not accumulate.

    Without this, one problem becomes three hundred rows in a fortnight
    and the table stops being able to answer what is open.
    """
    first = _post(client, _body(_divergence()))
    assert first.status_code == 201, first.text
    assert first.json()["first_seen"] == 1

    second = _post(client, _body(_divergence()))
    assert second.status_code == 201, second.text
    assert second.json() == {
        **second.json(),
        "first_seen": 0,
        "seen_again": 1,
    }


def test_a_different_source_is_a_different_finding(client: TestClient) -> None:
    """Identity includes both sources, not just the subject.

    The same route disagreeing with two different sources is two problems
    to look at, not one, and collapsing them would hide the second.
    """
    _post(client, _body(_divergence()))

    other = _divergence(
        right=_fact(
            "culprit@dev", "api/openapi.json", ConfidenceRank.COMMITTED_SPEC, value=False
        )
    )
    response = _post(client, _body(other))
    assert response.status_code == 201, response.text
    assert response.json()["first_seen"] == 1


@pytest.mark.asyncio
async def test_first_seen_at_does_not_move_on_a_repeat_sighting(
    migrated_database_url: str, role_database_url, db_engine: AsyncEngine
) -> None:
    """The column that answers "how long has this been broken".

    Refreshing it on every sighting would make every finding look new,
    which is the failure that makes a history table worthless.

    Driven through the service rather than the TestClient: the assertion
    is about two writes and what the row looks like between them, and
    reaching for the sync client from an async test to get at the engine
    would be more plumbing than the test is worth.
    """
    from app.divergences.service import store_divergences

    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE divergences CASCADE"))

    engine = create_async_engine(
        role_database_url("fact-writer", "FACT_WRITER_DB_PASSWORD")
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        monday = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        friday = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)

        async with factory() as session:
            first = await store_divergences(session, [_divergence()], None, now=monday)
        assert first.first_seen == 1

        async with factory() as session:
            again = await store_divergences(session, [_divergence()], None, now=friday)
        assert again.seen_again == 1
        assert again.first_seen == 0

        async with db_engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT first_seen_at, last_seen_at FROM divergences")
                )
            ).one()
        assert row.first_seen_at == monday, "first_seen_at moved on a repeat sighting"
        assert row.last_seen_at == friday, "last_seen_at did not move"
    finally:
        await engine.dispose()


# --- what the endpoint refuses ------------------------------------------


def test_a_capture_id_that_names_nothing_is_refused(client: TestClient) -> None:
    """A dangling link is worse than no link: it looks like one."""
    response = _post(client, _body(_divergence(), capture_id=uuid.uuid4()))
    assert response.status_code == 422, response.text


def test_a_divergence_whose_sides_disagree_is_refused(client: TestClient) -> None:
    """Two answers to one question, or it is not a divergence.

    Enforced by the model itself, so FastAPI refuses it before any
    application code runs — which is why this asserts a 422 and not a
    handled error.
    """
    payload = _body(_divergence())
    payload["divergences"][0]["right"]["subject"] = build(
        "http", component="orders-api", method="GET", path="/something-else"
    )
    assert _post(client, payload).status_code == 422


def test_a_divergence_cannot_be_built_around_a_config_value() -> None:
    """Phase 29 field 12, at the last place a value could be written down.

    A divergence embeds two whole facts, so every guarantee the fact model
    makes has to survive being nested inside one. It does, and structurally:
    `Fact` refuses a literal config value without a grant_ref, so a
    divergence carrying one cannot be constructed, let alone posted or
    stored. Asserted directly rather than left as an inference.
    """
    config_subject = build("config", component="orders-api", key="DATABASE_URL")
    with pytest.raises(ValueError) as caught:
        Fact(  # pyright: ignore[reportArgumentType]
            plane=Plane.INTENT,
            subject=config_subject,
            predicate="example_shape",
            value=LEAKED,
            provenance=Provenance(
                source_kind=SourceKind.SPEC,
                extractor="culprit@dev",
                confidence_rank=ConfidenceRank.COMMITTED_SPEC,
            ),
            captured_at=datetime.now(UTC),
            capture_id=CAPTURE,
        )
    assert "hunter2" not in str(caught.value), "the refusal echoed the value it refused"
