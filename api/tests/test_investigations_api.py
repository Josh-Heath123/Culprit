"""`POST /investigations` and the reads (Phase 32, part 2), against a real
database under the real roles: `investigation-writer` for the write,
`api-reader` for every read.

The round trip runs on investigations the fault library recorded from real
walks (tests/data/investigations/, written by `CULPRIT_FAULT_LIBRARY_RECORD`)
— the API is tested on what `culprit diagnose` actually writes. The
database's own hold on field 7's rule is shown by direct SQL as the writer,
not through the API, because the point is that a writer which skips the
model still cannot store an uncited edge.
"""

import importlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from culprit_model.investigations import Investigation
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
ORDERS = build("component", name="orders")
ORDERS_DSN = build("config", component="orders", key="DATABASE_URL")
AUDIENCE = build(
    "auth", from_component="order-service", to_component="inventory-service", aspect="audience"
)
RECORDED = sorted((Path(__file__).parent / "data" / "investigations").glob("*.json"))


def _recorded(name: str) -> dict:
    return json.loads(
        (Path(__file__).parent / "data" / "investigations" / f"{name}.json").read_text("utf-8")
    )


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE investigations CASCADE"))

    os.environ["INVESTIGATION_WRITER_DATABASE_URL"] = role_database_url(
        "investigation-writer", "INVESTIGATION_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN
    from app.facts import dependencies as facts_dependencies
    from app.investigations import config as investigations_config

    importlib.reload(investigations_config)
    importlib.reload(facts_dependencies)
    from app.investigations import router as router_module

    importlib.reload(router_module)

    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker

    writer = create_async_engine(investigations_config.INVESTIGATION_WRITER_DATABASE_URL)
    reader = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    app = FastAPI()
    app.state.investigation_writer_session_factory = async_sessionmaker(
        writer, expire_on_commit=False
    )
    app.state.session_factory = async_sessionmaker(reader, expire_on_commit=False)
    install_error_handlers(app)
    app.include_router(router_module.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}

    with TestClient(app) as test_client:
        yield test_client

    await writer.dispose()
    await reader.dispose()


def _post(client: TestClient, payload: dict, token: str | None = PROJECT_TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/investigations", json=payload, headers=headers)


# ---- the round trip --------------------------------------------------------------


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.stem)
def test_a_recorded_investigation_round_trips_whole(client: TestClient, path: Path) -> None:
    """Part 2's first criterion, on every investigation the fault library
    recorded — the audience one among them: what goes in is what comes back,
    root, edges, citations, rubric and symptom attestation, compared whole."""
    posted = Investigation.model_validate(json.loads(path.read_text("utf-8")))
    response = _post(client, posted.model_dump(mode="json"))
    assert response.status_code == 201, response.text

    stored = client.get(f"/investigations/{posted.id}")
    assert stored.status_code == 200, stored.text
    assert Investigation.model_validate(stored.json()) == posted

    tree = client.get(f"/investigations/{posted.id}/tree")
    assert tree.status_code == 200, tree.text
    body = tree.json()
    assert body["symptom"] == posted.symptom.model_dump(mode="json")
    assert body["diagnosis"] == (
        posted.diagnosis.model_dump(mode="json") if posted.diagnosis else None
    )
    edges = [
        {k: e[k] for k in ("from_subject", "to_subject", "relation", "established_by")}
        for e in body["fault_tree"]
    ]
    assert edges == [e.model_dump(mode="json") for e in posted.fault_tree]
    # Every edge carries the readings it cites, and only those.
    for edge in body["fault_tree"]:
        assert [r["id"] for r in edge["readings"]] == edge["established_by"]


def test_the_audience_investigation_comes_back_rooted_at_the_audience(
    client: TestClient,
) -> None:
    payload = _recorded("auth-audience")
    assert _post(client, payload).status_code == 201
    tree = client.get(f"/investigations/{payload['id']}/tree").json()
    assert tree["diagnosis"]["root_subject"] == AUDIENCE
    assert tree["diagnosis"]["complete"] is True
    assert tree["symptom"]["attestation"]["kind"] == "reported"
    assert set(tree["diagnosis"]["confidence"]) == {
        "reproduced",
        "discriminated",
        "counterfactual",
        "verified",
    }
    listing = client.get("/investigations").json()["items"]
    assert [i["id"] for i in listing] == [payload["id"]]
    assert listing[0]["attestation"] == "reported"


def test_untested_and_unexplored_are_kept_apart(client: TestClient) -> None:
    payload = _recorded("auth-audience-ungranted")
    assert _post(client, payload).status_code == 201
    groups = client.get(f"/investigations/{payload['id']}/tree").json()["hypotheses"]
    assert {h["kind"] for h in groups["unexplored"]} == {"auth_audience_mismatch"}
    assert "config.read.values" in groups["unexplored"][0]["reason"]
    assert all(h["status"] == "open" for h in groups["untested"])


# ---- the write path ---------------------------------------------------------------


def test_the_same_investigation_twice_is_a_409(client: TestClient) -> None:
    payload = _recorded("auth-audience")
    assert _post(client, payload).status_code == 201
    assert _post(client, payload).status_code == 409


def test_an_upload_needs_the_project_token(client: TestClient) -> None:
    assert _post(client, _recorded("auth-audience"), token=None).status_code == 401
    assert _post(client, _recorded("auth-audience"), token="wrong").status_code in (401, 403)


def test_credentials_in_free_text_are_redacted_on_the_way_in(client: TestClient) -> None:
    """Invariant 11: the endpoint redacts at the reading's choke point and
    does not trust the binary to have done it."""
    payload = _recorded("auth-audience-ungranted")
    leaked = "postgresql://svc:hunter2-not-real@db.internal:5432/app"
    payload["hypotheses"][0]["reason"] = f"could not connect to {leaked}"
    payload["readings"][0]["reading"]["measured"] = {"url": leaked}
    # Every free-text field, not just the obvious ones (invariant audit).
    payload["symptom"]["source"] = f"pager via {leaked}"
    payload["symptom"]["attestation"]["reported_by"] = f"ops ({leaked})"
    payload["diagnosis"]["statement"] = f"partial: {leaked}"
    for criterion in payload["diagnosis"]["confidence"].values():
        criterion["reason"] = f"see {leaked}"
    assert _post(client, payload).status_code == 201
    stored = client.get(f"/investigations/{payload['id']}").text
    assert "hunter2-not-real" not in stored


# ---- the database holds field 7's rule ------------------------------------------


async def _writer(role_database_url) -> AsyncEngine:
    return create_async_engine(
        role_database_url("investigation-writer", "INVESTIGATION_WRITER_DB_PASSWORD")
    )


async def _seed(conn, investigation_id: str, reading_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO investigations (id, opened_at, environment, symptom, ingested_at) "
            "VALUES (:id, now(), 'test', '{}'::jsonb, now())"
        ),
        {"id": investigation_id},
    )
    await conn.execute(
        text(
            "INSERT INTO investigation_readings "
            "(investigation_id, id, probe_id, target, verdict, reading) "
            "VALUES (:inv, :rid, 'probe.net.tcp_connect', :target, 'fail', '{}'::jsonb)"
        ),
        {"inv": investigation_id, "rid": reading_id, "target": ORDERS},
    )


_EDGE = (
    "INSERT INTO fault_edges (investigation_id, id, from_subject, to_subject, relation) "
    "VALUES (:inv, 0, :from_subject, :to_subject, 'caused_by')"
)
_SUBJECTS = {"from_subject": ORDERS, "to_subject": ORDERS_DSN}
_CITE = (
    "INSERT INTO fault_edge_readings (investigation_id, edge_id, reading_id) VALUES (:inv, 0, :rid)"
)


@pytest.mark.asyncio
async def test_the_database_stores_a_cited_edge(client: TestClient, role_database_url) -> None:
    """The positive control: without it, the two refusals below could pass
    because nothing at all could be inserted."""
    engine = await _writer(role_database_url)
    try:
        async with engine.begin() as conn:
            await _seed(conn, "inv-sql-ok", "r1")
            await conn.execute(text(_EDGE), {"inv": "inv-sql-ok", **_SUBJECTS})
            await conn.execute(text(_CITE), {"inv": "inv-sql-ok", "rid": "r1"})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_database_refuses_an_edge_with_no_reading(
    client: TestClient, role_database_url
) -> None:
    engine = await _writer(role_database_url)
    try:
        with pytest.raises(DBAPIError, match="cites no reading"):
            async with engine.begin() as conn:
                await _seed(conn, "inv-sql-uncited", "r1")
                await conn.execute(text(_EDGE), {"inv": "inv-sql-uncited", **_SUBJECTS})
                # No citation: refused when the transaction commits.
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_database_refuses_a_citation_into_another_investigation(
    client: TestClient, role_database_url
) -> None:
    engine = await _writer(role_database_url)
    try:
        async with engine.begin() as conn:
            await _seed(conn, "inv-sql-other", "r7")
        with pytest.raises(DBAPIError, match="fk_fault_edge_readings_reading"):
            async with engine.begin() as conn:
                await _seed(conn, "inv-sql-borrower", "r1")
                await conn.execute(text(_EDGE), {"inv": "inv-sql-borrower", **_SUBJECTS})
                # r7 exists — in the other investigation, not this one.
                await conn.execute(text(_CITE), {"inv": "inv-sql-borrower", "rid": "r7"})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_investigation_writer_can_only_append(
    client: TestClient, role_database_url
) -> None:
    engine = await _writer(role_database_url)
    try:
        for statement in (
            "SELECT * FROM investigations",
            "SELECT * FROM readings",
            "DELETE FROM investigations",
            "UPDATE investigations SET environment = 'x'",
            "INSERT INTO incident_candidates (status) VALUES ('open')",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_role_can_write_the_incident_tables(client: TestClient, role_database_url) -> None:
    """Part 2, item 7: the incident tables stay as history, read-only. The
    two roles that wrote them have lost every write; reads remain."""
    for role, password_env in (
        ("correlation-engine", "CORRELATION_ENGINE_DB_PASSWORD"),
        ("root-cause-writer", "ROOT_CAUSE_WRITER_DB_PASSWORD"),
    ):
        engine = create_async_engine(role_database_url(role, password_env))
        try:
            # Zero-row statements: Postgres checks the privilege before it
            # looks for rows, so these test the grant and nothing else.
            for statement in (
                "INSERT INTO incident_candidates SELECT * FROM incident_candidates WHERE false",
                "UPDATE incident_candidates SET status = status WHERE false",
                "INSERT INTO incident_anomalies SELECT * FROM incident_anomalies WHERE false",
            ):
                with pytest.raises(DBAPIError, match="permission denied"):
                    async with engine.begin() as conn:
                        await conn.execute(text(statement))
            async with engine.begin() as conn:
                await conn.execute(text("SELECT count(*) FROM incident_candidates"))
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_a_temp_table_cannot_shadow_the_citation_check(
    client: TestClient, role_database_url
) -> None:
    """The trigger's table is schema-qualified and pg_temp is searched last,
    so a writer's temp table named fault_edge_readings, holding a fake
    citation, cannot satisfy it (invariant audit, Phase 32 part 2)."""
    engine = await _writer(role_database_url)
    try:
        with pytest.raises(DBAPIError, match="cites no reading"):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "CREATE TEMP TABLE fault_edge_readings "
                        "(investigation_id text, edge_id int, reading_id text)"
                    )
                )
                await conn.execute(
                    text("INSERT INTO fault_edge_readings VALUES ('inv-sql-shadow', 0, 'r1')")
                )
                await _seed(conn, "inv-sql-shadow", "r1")
                await conn.execute(text(_EDGE), {"inv": "inv-sql-shadow", **_SUBJECTS})
    finally:
        await engine.dispose()
