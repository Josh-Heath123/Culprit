"""First real HTTP-level integration test in this codebase (Phase 14,
docs/SELF_HOSTED_PLAN.md) — drives app/registry/router.py through
FastAPI's TestClient against a real, migrated Postgres container
(see api/tests/conftest.py), not mocks.

Deliberately builds a minimal test app (registry_router mounted
directly, behind the same require_admin dependency app/main.py uses —
Phase 16 moved this router off the plain require_auth every other
router still less-strictly-gated router used) instead of importing
app.main's own `app` — app.main's lifespan also stands up an arq/Redis
connection pool for the root-cause-regeneration endpoint, which has
nothing to do with the registry and would make every test in this file
depend on a Redis container too, for no benefit.

Every import from app.* below is deferred into the `client` fixture
rather than sitting at module level: app.registry.router transitively
imports app.ingest_gateway.auth (via app.registry.keys, for the shared
_hash_key helper), and that module creates a DB engine at import time
from INGEST_GATEWAY_DATABASE_URL — importing any of this before
migrated_database_url has run would risk binding to whatever database
happened to be configured first, not necessarily this test's container.
"""

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency, see module docstring — unused otherwise
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE services, service_dependencies, api_keys CASCADE"))
        await conn.execute(text("TRUNCATE users CASCADE"))

    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    registry_admin_url = role_database_url("registry-admin", "REGISTRY_ADMIN_DB_PASSWORD")
    auth_service_url = role_database_url("auth-service", "AUTH_SERVICE_DB_PASSWORD")
    os.environ["API_READER_DATABASE_URL"] = api_reader_url
    os.environ["REGISTRY_ADMIN_DATABASE_URL"] = registry_admin_url
    os.environ["AUTH_SERVICE_DATABASE_URL"] = auth_service_url

    from app.auth.dependencies import require_admin
    from app.auth.repository import create_user
    from app.auth.security import create_access_token, hash_password
    from app.registry.router import router as registry_router
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    read_engine = create_async_engine(api_reader_url)
    write_engine = create_async_engine(registry_admin_url)
    auth_engine = create_async_engine(auth_service_url)

    app = FastAPI()
    app.state.session_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    app.state.registry_session_factory = async_sessionmaker(write_engine, expire_on_commit=False)
    app.include_router(registry_router, dependencies=[Depends(require_admin)])

    # require_admin needs a real users row (require_auth's own DB-backed
    # disabled-check reads it via api-reader) -- created directly via
    # the auth-service role rather than going through an HTTP endpoint,
    # same as test_users_api.py's _bootstrap_admin and for the same
    # reason (nothing can call POST /users before an admin exists yet).
    auth_session_factory = async_sessionmaker(auth_engine, expire_on_commit=False)
    async with auth_session_factory() as session:
        admin = await create_user(
            session,
            username="test-operator",
            password_hash=hash_password("unused-test-password"),
            role="admin",
        )
    await auth_engine.dispose()

    token = create_access_token(admin)
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client

    await read_engine.dispose()
    await write_engine.dispose()


def _create(client: TestClient, name: str, **kwargs) -> dict:
    response = client.post("/services", json={"name": name, **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_returns_service_and_one_time_key(client: TestClient) -> None:
    body = _create(client, "checkout-api", display_name="Checkout API")
    assert body["service"]["name"] == "checkout-api"
    assert body["service"]["display_name"] == "Checkout API"
    assert body["service"]["disabled"] is False
    assert body["service"]["depends_on"] == []
    assert len(body["service"]["keys"]) == 1
    assert body["service"]["keys"][0]["revoked"] is False
    assert body["api_key"].startswith("clp_live_")


def test_duplicate_name_rejected(client: TestClient) -> None:
    _create(client, "checkout-api")
    response = client.post("/services", json={"name": "checkout-api"})
    assert response.status_code == 409


def test_invalid_name_rejected(client: TestClient) -> None:
    response = client.post("/services", json={"name": "Not Valid!"})
    assert response.status_code == 422


def test_unknown_dependency_rejected(client: TestClient) -> None:
    response = client.post(
        "/services", json={"name": "checkout-api", "depends_on": ["ghost-service"]}
    )
    assert response.status_code == 400


def test_list_includes_created_service(client: TestClient) -> None:
    _create(client, "checkout-api")
    response = client.get("/services")
    assert response.status_code == 200
    names = [s["name"] for s in response.json()["items"]]
    assert "checkout-api" in names


def test_patch_updates_display_name_metrics_and_depends_on(client: TestClient) -> None:
    _create(client, "inventory-api")
    checkout = _create(client, "checkout-api")["service"]

    response = client.patch(
        f"/services/{checkout['id']}",
        json={
            "display_name": "Checkout",
            "monitored_metrics": ["http.server.duration"],
            "depends_on": ["inventory-api"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Checkout"
    assert body["monitored_metrics"] == ["http.server.duration"]
    assert body["depends_on"] == ["inventory-api"]


def test_patch_omitted_fields_are_left_alone(client: TestClient) -> None:
    checkout = _create(client, "checkout-api", display_name="Checkout")["service"]

    response = client.patch(f"/services/{checkout['id']}", json={"sort_order": 5})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Checkout"
    assert response.json()["sort_order"] == 5


def test_soft_delete_disables_but_keeps_the_service(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["service"]

    response = client.delete(f"/services/{checkout['id']}")
    assert response.status_code == 204

    get_response = client.get(f"/services/{checkout['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["disabled"] is True


def test_purge_hard_deletes_the_service(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["service"]

    response = client.delete(f"/services/{checkout['id']}?purge=true")
    assert response.status_code == 204

    assert client.get(f"/services/{checkout['id']}").status_code == 404


def test_issue_and_revoke_key(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["service"]

    issue_response = client.post(f"/services/{checkout['id']}/keys", json={"label": "rotation"})
    assert issue_response.status_code == 201
    issued = issue_response.json()
    assert issued["api_key"].startswith("clp_live_")
    assert issued["label"] == "rotation"

    revoke_response = client.delete(f"/services/{checkout['id']}/keys/{issued['key_id']}")
    assert revoke_response.status_code == 204

    service = client.get(f"/services/{checkout['id']}").json()
    revoked_key = next(k for k in service["keys"] if k["id"] == issued["key_id"])
    assert revoked_key["revoked"] is True


def test_no_key_material_ever_appears_in_a_response(client: TestClient) -> None:
    created = _create(client, "checkout-api")
    plaintext_key = created["api_key"]
    service_id = created["service"]["id"]
    client.post(f"/services/{service_id}/keys", json={"label": "second"})

    list_response = client.get("/services")
    detail_response = client.get(f"/services/{service_id}")

    for response in (list_response, detail_response):
        # The concern this guards against is a field like `key_hash`
        # getting added back to ServiceOut/KeyOut later, not just the
        # value of a hash the tests happen to know — searching for the
        # field name itself, not a specific hash, is what catches that.
        assert "key_hash" not in response.text
        assert plaintext_key not in response.text
