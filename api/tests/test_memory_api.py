"""HTTP-level integration tests for the engineering-memory API (Phase 21,
docs/AI_NATIVE_PLAN.md), following test_postmortems_api.py's pattern
exactly: a minimal FastAPI app (memory_router only) against a real,
migrated Postgres container (see conftest.py), not mocks.

Every import from app.* is deferred into the `client` fixture, same
reasoning as test_postmortems_api.py's own docstring — app.memory.router
creates a DB engine at import time from POSTMORTEM_WRITER_DATABASE_URL
(reused from app/postmortems/config.py, not a new one — invariant 10),
which must not bind before migrated_database_url has set the real
container's env vars.

AGENT_AUTOMATION_TOKEN is loaded from api/.env by conftest.py's own
load_dotenv() call, which runs before any test module is imported — the
dev value there ("dev-agent-automation-token") is what
require_auth_or_agent compares against below; it's never re-set here.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class _FakeArqPool:
    """No real Redis/arq in this test file (same reasoning
    test_postmortems_api.py gives) — just records what would have been
    enqueued."""

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
        await conn.execute(
            text(
                "TRUNCATE architecture_decisions, ai_change_records, "
                "invariant_violations, incident_change_links, incident_candidates CASCADE"
            )
        )
        await conn.execute(text("TRUNCATE users CASCADE"))

    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    postmortem_writer_url = role_database_url("postmortem-writer", "POSTMORTEM_WRITER_DB_PASSWORD")
    auth_service_url = role_database_url("auth-service", "AUTH_SERVICE_DB_PASSWORD")
    os.environ["API_READER_DATABASE_URL"] = api_reader_url
    os.environ["POSTMORTEM_WRITER_DATABASE_URL"] = postmortem_writer_url
    os.environ["AUTH_SERVICE_DATABASE_URL"] = auth_service_url

    from app.auth.repository import create_user
    from app.auth.security import create_access_token, hash_password
    from app.memory.router import router as memory_router
    from sqlalchemy.ext.asyncio import async_sessionmaker

    read_engine = create_async_engine(api_reader_url)
    write_engine = create_async_engine(postmortem_writer_url)
    auth_engine = create_async_engine(auth_service_url)

    app = FastAPI()
    app.state.session_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    app.state.postmortem_session_factory = async_sessionmaker(write_engine, expire_on_commit=False)
    app.state.arq_pool = _FakeArqPool()
    # No router-level dependency (unlike test_postmortems_api.py's own
    # fixture) — app/memory/router.py gates each endpoint individually.
    app.include_router(memory_router)

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


AGENT_TOKEN = "dev-agent-automation-token"  # matches api/.env, loaded by conftest.py


def _arq_pool(client: TestClient) -> _FakeArqPool:
    return client.app.state.arq_pool  # type: ignore[attr-defined]


# --- Architecture decisions -----------------------------------------------


def _create_decision(
    client: TestClient, title: str = "Use Postgres for everything", **kwargs
) -> dict:
    body = {"title": title, "body": "Because one database is simpler to operate.", **kwargs}
    response = client.post("/architecture-decisions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_decision_returns_pending_with_author(client: TestClient) -> None:
    body = _create_decision(client, title="Adopt trunk-based development")
    assert body["title"] == "Adopt trunk-based development"
    assert body["embedding_status"] == "pending"
    assert body["embedding_error"] is None
    assert body["author_user_id"] is not None
    assert body["updated_at"] is None


def test_create_decision_enqueues_embed_job(client: TestClient) -> None:
    created = _create_decision(client)
    assert _arq_pool(client).enqueued == [("embed_architecture_decision", (created["id"],))]


def test_create_decision_rejects_empty_title_or_body(client: TestClient) -> None:
    empty_title = client.post("/architecture-decisions", json={"title": "", "body": "x"})
    assert empty_title.status_code == 422
    empty_body = client.post("/architecture-decisions", json={"title": "x", "body": ""})
    assert empty_body.status_code == 422


def test_list_decisions_truncates_body(client: TestClient) -> None:
    long_body = "x" * 500
    _create_decision(client, title="Long one", body=long_body)

    response = client.get("/architecture-decisions")
    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["title"] == "Long one")
    assert len(item["body"]) < len(long_body)
    assert item["body"].endswith("…")


def test_get_decision_detail_returns_full_body(client: TestClient) -> None:
    long_body = "x" * 500
    created = _create_decision(client, title="Long one", body=long_body)

    response = client.get(f"/architecture-decisions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["body"] == long_body


def test_get_missing_decision_404s(client: TestClient) -> None:
    assert client.get(f"/architecture-decisions/{uuid4()}").status_code == 404


def test_patch_decision_title_only_does_not_enqueue(client: TestClient) -> None:
    created = _create_decision(client)
    _arq_pool(client).enqueued.clear()

    response = client.patch(f"/architecture-decisions/{created['id']}", json={"title": "Renamed"})
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["updated_at"] is not None
    assert _arq_pool(client).enqueued == []


def test_patch_decision_body_change_enqueues(client: TestClient) -> None:
    created = _create_decision(client)
    _arq_pool(client).enqueued.clear()

    response = client.patch(
        f"/architecture-decisions/{created['id']}", json={"body": "New reasoning."}
    )
    assert response.status_code == 200
    assert _arq_pool(client).enqueued == [("embed_architecture_decision", (created["id"],))]


def test_delete_decision_removes_it(client: TestClient) -> None:
    created = _create_decision(client)
    assert client.delete(f"/architecture-decisions/{created['id']}").status_code == 204
    assert client.get(f"/architecture-decisions/{created['id']}").status_code == 404


def test_delete_missing_decision_404s(client: TestClient) -> None:
    assert client.delete(f"/architecture-decisions/{uuid4()}").status_code == 404


def test_no_embedding_vector_in_decision_responses(client: TestClient) -> None:
    created = _create_decision(client)
    list_response = client.get("/architecture-decisions")
    detail_response = client.get(f"/architecture-decisions/{created['id']}")
    for response in (list_response, detail_response):
        assert '"embedding"' not in response.text


# --- AI change records ------------------------------------------------------


def _change_payload(commit_sha: str, **kwargs) -> dict:
    return {
        "commit_sha": commit_sha,
        "summary": "Fix the flaky retry test",
        "files_changed": ["worker/app/rag/embed_job.py"],
        "git_author": "Test Author <test@example.com>",
        "committed_at": datetime.now(UTC).isoformat(),
        **kwargs,
    }


def test_create_change_record_via_agent_token_has_no_author(client: TestClient) -> None:
    response = client.post(
        "/ai-change-records",
        json=_change_payload("a" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["author_user_id"] is None
    assert body["embedding_status"] == "pending"
    assert body["files_changed"] == ["worker/app/rag/embed_job.py"]


def test_create_change_record_via_user_jwt_has_author(client: TestClient) -> None:
    # No explicit Authorization override -- the client fixture's own
    # default header is a real user's JWT.
    response = client.post("/ai-change-records", json=_change_payload("b" * 40))
    assert response.status_code == 201, response.text
    assert response.json()["author_user_id"] is not None


def test_create_change_record_rejects_missing_or_wrong_credential(client: TestClient) -> None:
    no_auth = client.post(
        "/ai-change-records", json=_change_payload("c" * 40), headers={"Authorization": ""}
    )
    assert no_auth.status_code == 401

    wrong_token = client.post(
        "/ai-change-records",
        json=_change_payload("d" * 40),
        headers={"Authorization": "Bearer not-the-right-token"},
    )
    assert wrong_token.status_code == 401


def test_create_change_record_enqueues_embed_job(client: TestClient) -> None:
    response = client.post(
        "/ai-change-records",
        json=_change_payload("e" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    record_id = response.json()["id"]
    assert _arq_pool(client).enqueued == [("embed_ai_change_record", (record_id,))]


def test_create_change_record_same_commit_sha_is_idempotent(client: TestClient) -> None:
    sha = "f" * 40
    first = client.post(
        "/ai-change-records",
        json=_change_payload(sha),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert first.status_code == 201
    _arq_pool(client).enqueued.clear()

    second = client.post(
        "/ai-change-records",
        json=_change_payload(sha, summary="a different summary, ignored"),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    # The original summary survives -- the second POST is a no-op, not an update.
    assert second.json()["summary"] == first.json()["summary"]
    # No re-embed for a no-op create.
    assert _arq_pool(client).enqueued == []

    listing = client.get("/ai-change-records")
    matching = [item for item in listing.json()["items"] if item["commit_sha"] == sha]
    assert len(matching) == 1


def test_list_change_records_since_filter(client: TestClient) -> None:
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    old = _change_payload("1" * 40, committed_at=two_days_ago)
    recent = _change_payload("2" * 40, committed_at=datetime.now(UTC).isoformat())
    for payload in (old, recent):
        response = client.post(
            "/ai-change-records",
            json=payload,
            headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
        )
        assert response.status_code == 201

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    # params=, not an f-string into the URL -- the ISO datetime's own
    # "+00:00" offset would otherwise have its "+" decoded as a literal
    # space by query-string parsing, corrupting the value.
    response = client.get("/ai-change-records", params={"since": since})
    assert response.status_code == 200, response.text
    shas = {item["commit_sha"] for item in response.json()["items"]}
    assert shas == {"2" * 40}


def test_get_missing_change_record_404s(client: TestClient) -> None:
    assert client.get(f"/ai-change-records/{uuid4()}").status_code == 404


def test_no_embedding_vector_in_change_record_responses(client: TestClient) -> None:
    response = client.post(
        "/ai-change-records",
        json=_change_payload("9" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    record_id = response.json()["id"]
    for r in (client.get("/ai-change-records"), client.get(f"/ai-change-records/{record_id}")):
        assert '"embedding"' not in r.text


def test_change_record_detail_starts_with_no_links_or_violations(client: TestClient) -> None:
    created = client.post(
        "/ai-change-records",
        json=_change_payload("d" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    ).json()
    detail = client.get(f"/ai-change-records/{created['id']}").json()
    assert detail["linked_incident_ids"] == []
    assert detail["violations"] == []


async def test_change_record_detail_shows_persisted_violation(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Phase 23 (docs/AI_NATIVE_PLAN.md): a violation with
    ai_change_record_id set can only happen via a direct DB write today
    (Known Trap 1 -- the hook-time write path this phase actually builds
    always leaves it NULL) — inserted directly here via the superuser
    engine, not through the API, to prove the *read* side works."""
    created = client.post(
        "/ai-change-records",
        json=_change_payload("v" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    ).json()
    record_id = created["id"]

    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO invariant_violations "
                "(invariant_name, file_paths, message, ai_change_record_id) "
                "VALUES ('coupled_files', '[\"a\", \"b\"]'::jsonb, "
                "'\"a\" changed but its declared pair \"b\" did not', :record_id)"
            ),
            {"record_id": record_id},
        )

    detail = client.get(f"/ai-change-records/{record_id}").json()
    assert len(detail["violations"]) == 1
    violation = detail["violations"][0]
    assert violation["invariant_name"] == "coupled_files"
    assert violation["file_paths"] == ["a", "b"]


async def test_change_record_detail_shows_linked_incident(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Same reasoning as the violation test above — worker/app/memory/
    link_job.py is what actually creates incident_change_links rows in
    production; inserted directly here to prove the API's read side."""
    created = client.post(
        "/ai-change-records",
        json=_change_payload("l" * 40),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    ).json()
    record_id = created["id"]
    incident_id = str(uuid4())

    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO incident_candidates (id, opened_at, last_anomaly_at, status) "
                "VALUES (:incident_id, now(), now(), 'open')"
            ),
            {"incident_id": incident_id},
        )
        await conn.execute(
            text(
                "INSERT INTO incident_change_links "
                "(incident_id, ai_change_record_id, link_reason) "
                "VALUES (:incident_id, :record_id, 'order-service anomaly 14m after this change')"
            ),
            {"incident_id": incident_id, "record_id": record_id},
        )

    detail = client.get(f"/ai-change-records/{record_id}").json()
    assert detail["linked_incident_ids"] == [incident_id]


# --- Invariant violations ---------------------------------------------------


def _violation_payload(**kwargs) -> dict:
    return {
        "invariant_name": "coupled_files",
        "file_paths": ["worker/app/db.py", "api/app/db/models.py"],
        "message": '"worker/app/db.py" changed but its declared pair '
        '"api/app/db/models.py" did not',
        **kwargs,
    }


def test_create_violation_via_agent_token(client: TestClient) -> None:
    response = client.post(
        "/invariant-violations",
        json=_violation_payload(),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invariant_name"] == "coupled_files"
    assert body["file_paths"] == ["worker/app/db.py", "api/app/db/models.py"]


def test_create_violation_via_user_jwt(client: TestClient) -> None:
    # No explicit Authorization override -- the client fixture's default
    # header is a real user's JWT, same as ai-change-records' own test.
    response = client.post("/invariant-violations", json=_violation_payload())
    assert response.status_code == 201, response.text


def test_create_violation_rejects_missing_or_wrong_credential(client: TestClient) -> None:
    no_auth = client.post(
        "/invariant-violations", json=_violation_payload(), headers={"Authorization": ""}
    )
    assert no_auth.status_code == 401

    wrong_token = client.post(
        "/invariant-violations",
        json=_violation_payload(),
        headers={"Authorization": "Bearer not-the-right-token"},
    )
    assert wrong_token.status_code == 401


def test_create_violation_rejects_unknown_invariant_name(client: TestClient) -> None:
    response = client.post(
        "/invariant-violations",
        json=_violation_payload(invariant_name="something_else"),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 422


def test_create_violation_rejects_empty_message(client: TestClient) -> None:
    response = client.post(
        "/invariant-violations",
        json=_violation_payload(message=""),
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    assert response.status_code == 422


# --- Least privilege ---------------------------------------------------------


async def test_api_reader_cannot_write_to_architecture_decisions(role_database_url) -> None:
    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    engine = create_async_engine(api_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO architecture_decisions (title, body) VALUES ('x', 'y')")
                )
    finally:
        await engine.dispose()


async def test_api_reader_cannot_write_to_ai_change_records(role_database_url) -> None:
    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    engine = create_async_engine(api_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO ai_change_records (commit_sha, summary, committed_at) "
                        "VALUES ('deadbeef', 'x', now())"
                    )
                )
    finally:
        await engine.dispose()


async def test_api_reader_cannot_write_to_invariant_violations(role_database_url) -> None:
    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    engine = create_async_engine(api_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO invariant_violations (invariant_name, message) "
                        "VALUES ('coupled_files', 'x')"
                    )
                )
    finally:
        await engine.dispose()


async def test_api_reader_cannot_write_to_incident_change_links(role_database_url) -> None:
    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    engine = create_async_engine(api_reader_url)
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO incident_change_links "
                        "(incident_id, ai_change_record_id, link_reason) "
                        "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')"
                    )
                )
    finally:
        await engine.dispose()


async def test_correlation_engine_can_read_ai_change_records_and_write_links(
    role_database_url, db_engine: AsyncEngine
) -> None:
    """Phase 23: worker/app/memory/link_job.py runs under exactly this
    role -- a real, migrated-role proof that its grants (added by this
    phase's own migration, not shown in the plan's own illustrative SQL
    block -- see that migration's module docstring) actually work.
    worker/tests/test_link_job.py never touches real Postgres roles at
    all (it bypasses Alembic entirely, per that file's own docstring),
    so this is the only place either grant is actually exercised."""
    correlation_engine_url = role_database_url(
        "correlation-engine", "CORRELATION_ENGINE_DB_PASSWORD"
    )
    engine = create_async_engine(correlation_engine_url)
    try:
        record_id, incident_id = str(uuid4()), str(uuid4())
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ai_change_records (id, commit_sha, summary, committed_at) "
                    "VALUES (:id, 'deadbeefcafe', 'x', now())"
                ),
                {"id": record_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO incident_candidates (id, opened_at, last_anomaly_at, status) "
                    "VALUES (:id, now(), now(), 'open')"
                ),
                {"id": incident_id},
            )

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT commit_sha FROM ai_change_records WHERE id = :id"), {"id": record_id}
            )
            assert result.scalar_one() == "deadbeefcafe"

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO incident_change_links "
                    "(incident_id, ai_change_record_id, link_reason) "
                    "VALUES (:incident_id, :record_id, 'test')"
                ),
                {"incident_id": incident_id, "record_id": record_id},
            )
    finally:
        await engine.dispose()
