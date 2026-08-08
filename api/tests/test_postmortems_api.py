"""HTTP-level integration tests for the postmortem write path (Phase 18,
docs/SELF_HOSTED_PLAN.md), following test_registry_api.py's pattern
exactly: a minimal FastAPI app (postmortems_router only, behind
require_auth — not require_admin, unlike registry/users) against a real,
migrated Postgres container (see conftest.py), not mocks.

Every import from app.* is deferred into the `client` fixture, same
reasoning as test_registry_api.py's own docstring: app.postmortems.router
transitively imports app.ingest_gateway.auth (via app.registry.keys ->
... no, actually via nothing here — postmortems doesn't touch the
registry — but it does create a DB engine at import time from
POSTMORTEM_WRITER_DATABASE_URL (app/postmortems/config.py), which must
not bind before migrated_database_url has set the real container's
env vars.
"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class _FakeArqPool:
    """No real Redis/arq in this test file (same reasoning
    test_registry_api.py gives for not importing app.main's own `app`) —
    just records what would have been enqueued."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple]] = []

    async def enqueue_job(self, function: str, *args: object) -> None:
        self.enqueued.append((function, args))


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency, see module docstring
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE postmortems CASCADE"))
        await conn.execute(text("TRUNCATE users CASCADE"))

    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    postmortem_writer_url = role_database_url("postmortem-writer", "POSTMORTEM_WRITER_DB_PASSWORD")
    auth_service_url = role_database_url("auth-service", "AUTH_SERVICE_DB_PASSWORD")
    os.environ["API_READER_DATABASE_URL"] = api_reader_url
    os.environ["POSTMORTEM_WRITER_DATABASE_URL"] = postmortem_writer_url
    os.environ["AUTH_SERVICE_DATABASE_URL"] = auth_service_url

    from app.auth.dependencies import require_auth
    from app.auth.repository import create_user
    from app.auth.security import create_access_token, hash_password
    from app.postmortems.router import router as postmortems_router
    from sqlalchemy.ext.asyncio import async_sessionmaker

    read_engine = create_async_engine(api_reader_url)
    write_engine = create_async_engine(postmortem_writer_url)
    auth_engine = create_async_engine(auth_service_url)

    app = FastAPI()
    app.state.session_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    app.state.postmortem_session_factory = async_sessionmaker(write_engine, expire_on_commit=False)
    app.state.arq_pool = _FakeArqPool()
    app.include_router(postmortems_router, dependencies=[Depends(require_auth)])

    auth_session_factory = async_sessionmaker(auth_engine, expire_on_commit=False)
    async with auth_session_factory() as session:
        user = await create_user(
            session,
            username="test-member",
            password_hash=hash_password("unused-test-password"),
            role="member",
        )
    await auth_engine.dispose()

    token = create_access_token(user)
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client

    await read_engine.dispose()
    await write_engine.dispose()


def _create(client: TestClient, title: str = "Test postmortem", **kwargs) -> dict:
    body = {"title": title, "body": "Summary: something happened.", **kwargs}
    response = client.post("/postmortems", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _arq_pool(client: TestClient) -> _FakeArqPool:
    return client.app.state.arq_pool  # type: ignore[attr-defined]


def test_create_returns_postmortem_with_pending_status(client: TestClient) -> None:
    body = _create(client, title="A new incident writeup")
    assert body["title"] == "A new incident writeup"
    assert body["embedding_status"] == "pending"
    assert body["embedding_error"] is None
    # Set to the authenticated caller, not left null — see
    # app/postmortems/router.py's create_postmortem_endpoint.
    assert body["author_user_id"] is not None
    assert body["updated_at"] is None


def test_create_enqueues_embed_job(client: TestClient) -> None:
    created = _create(client)
    assert _arq_pool(client).enqueued == [("embed_postmortem", (created["id"],))]


def test_create_rejects_empty_title_or_body(client: TestClient) -> None:
    assert client.post("/postmortems", json={"title": "", "body": "x"}).status_code == 422
    assert client.post("/postmortems", json={"title": "x", "body": ""}).status_code == 422


def test_create_with_unknown_incident_id_rejected(client: TestClient) -> None:
    response = client.post(
        "/postmortems", json={"title": "x", "body": "y", "incident_id": str(uuid4())}
    )
    assert response.status_code == 400


def test_list_includes_created_postmortem_with_truncated_body(client: TestClient) -> None:
    long_body = "x" * 500
    _create(client, title="Long one", body=long_body)

    response = client.get("/postmortems")
    assert response.status_code == 200
    body = response.json()
    item = next(item for item in body["items"] if item["title"] == "Long one")
    assert len(item["body"]) < len(long_body)
    assert item["body"].endswith("…")


def test_get_detail_returns_full_body(client: TestClient) -> None:
    long_body = "x" * 500
    created = _create(client, title="Long one", body=long_body)

    response = client.get(f"/postmortems/{created['id']}")
    assert response.status_code == 200
    assert response.json()["body"] == long_body


def test_get_missing_postmortem_404s(client: TestClient) -> None:
    assert client.get(f"/postmortems/{uuid4()}").status_code == 404


def test_patch_title_only_does_not_enqueue(client: TestClient) -> None:
    created = _create(client)
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/postmortems/{created['id']}", json={"title": "Renamed"})
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["updated_at"] is not None
    assert _arq_pool(client).enqueued == []


def test_patch_body_change_enqueues(client: TestClient) -> None:
    created = _create(client)
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/postmortems/{created['id']}", json={"body": "A different body."})
    assert response.status_code == 200
    assert _arq_pool(client).enqueued == [("embed_postmortem", (created["id"],))]


def test_patch_body_unchanged_does_not_enqueue(client: TestClient) -> None:
    created = _create(client, body="Same body throughout.")
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/postmortems/{created['id']}", json={"body": "Same body throughout."})
    assert response.status_code == 200
    assert _arq_pool(client).enqueued == []


async def test_empty_patch_on_failed_postmortem_retries(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    created = _create(client)
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE postmortems SET embedding_error = :err WHERE id = :id"),
            {"err": "Voyage rate limit: too many requests", "id": created["id"]},
        )
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/postmortems/{created['id']}", json={})
    assert response.status_code == 200
    assert response.json()["embedding_status"] == "failed"
    assert _arq_pool(client).enqueued == [("embed_postmortem", (created["id"],))]
    # A pure retry (no title/body in the payload) must not look like a
    # content edit — see service.py::patch_postmortem's docstring.
    assert response.json()["updated_at"] is None


def test_empty_patch_on_healthy_postmortem_does_not_enqueue(client: TestClient) -> None:
    created = _create(client)
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/postmortems/{created['id']}", json={})
    assert response.status_code == 200
    assert _arq_pool(client).enqueued == []


async def test_embedding_status_embedded_when_embedded_at_set(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    created = _create(client)
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE postmortems SET embedded_at = now() WHERE id = :id"),
            {"id": created["id"]},
        )

    response = client.get(f"/postmortems/{created['id']}")
    assert response.json()["embedding_status"] == "embedded"


async def test_embedding_status_failed_wins_over_a_stale_embedded_at(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """A postmortem that was embedded once, then edited, then failed to
    re-embed still has an old embedded_at set — must read as "failed",
    not "embedded", since the current body no longer matches what was
    actually embedded (service.py::_embedding_status's own docstring)."""
    created = _create(client)
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE postmortems SET embedded_at = now(), embedding_error = :err WHERE id = :id"
            ),
            {"err": "rate limited", "id": created["id"]},
        )

    response = client.get(f"/postmortems/{created['id']}")
    assert response.json()["embedding_status"] == "failed"


def test_delete_removes_postmortem(client: TestClient) -> None:
    created = _create(client)
    assert client.delete(f"/postmortems/{created['id']}").status_code == 204
    assert client.get(f"/postmortems/{created['id']}").status_code == 404


def test_delete_missing_postmortem_404s(client: TestClient) -> None:
    assert client.delete(f"/postmortems/{uuid4()}").status_code == 404


def test_no_embedding_vector_ever_appears_in_a_response(client: TestClient) -> None:
    created = _create(client)
    list_response = client.get("/postmortems")
    detail_response = client.get(f"/postmortems/{created['id']}")
    for response in (list_response, detail_response):
        assert '"embedding"' not in response.text


async def test_api_reader_cannot_write_to_postmortems(role_database_url) -> None:
    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    engine = create_async_engine(api_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO postmortems (title, body) VALUES ('x', 'y')"))
    finally:
        await engine.dispose()
