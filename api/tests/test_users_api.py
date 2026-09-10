"""HTTP-level integration tests for Phase 16's auth/users API — drives
the real routers through FastAPI's TestClient against a real, migrated
Postgres container (see api/tests/conftest.py), same approach as
test_registry_api.py.

Builds a test app mounting auth_router (self-service, no router-level
gate — /login must stay reachable unauthenticated) alongside
users_router AND the model router, both under require_admin — the
acceptance criterion this file proves isn't just "admin CRUD works," it's
"a member's token gets 403 from POST /model/components too," i.e. require_admin
actually enforces across every router it's applied to, not just the one
this file happens to be named after.
"""

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from app.incidents.limiter import limiter
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency, see conftest — unused otherwise
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
        await conn.execute(text("TRUNCATE components, connections, api_keys CASCADE"))

    # app.incidents.limiter.limiter is a module-level singleton shared by
    # every router that rate-limits (POST /auth/login here) — its
    # in-memory bucket storage persists across tests in the same
    # process. Reset it per test the same way the DB gets TRUNCATEd
    # above, or an earlier test's login attempts count against this
    # one's limit (every TestClient request reports the same fake
    # "testclient" address, so they'd all share one bucket).
    limiter.reset()

    api_reader_url = role_database_url("api-reader", "API_READER_PASSWORD")
    auth_service_url = role_database_url("auth-service", "AUTH_SERVICE_DB_PASSWORD")
    registry_admin_url = role_database_url("registry-admin", "REGISTRY_ADMIN_DB_PASSWORD")
    os.environ["API_READER_DATABASE_URL"] = api_reader_url
    os.environ["AUTH_SERVICE_DATABASE_URL"] = auth_service_url
    os.environ["REGISTRY_ADMIN_DATABASE_URL"] = registry_admin_url

    # Deferred imports: these transitively import app.ingest_gateway.auth
    # (via app.registry.keys) and read *_DATABASE_URL at import time in
    # places — see test_registry_api.py's own module docstring for why
    # this can't sit at module level.
    from app.auth.dependencies import require_admin
    from app.auth.router import router as auth_router
    from app.auth.users_router import router as users_router
    from app.model.router import router as model_router
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    read_engine = create_async_engine(api_reader_url)
    auth_engine = create_async_engine(auth_service_url)
    registry_engine = create_async_engine(registry_admin_url)

    app = FastAPI()
    app.state.session_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    app.state.auth_session_factory = async_sessionmaker(auth_engine, expire_on_commit=False)
    app.state.registry_session_factory = async_sessionmaker(registry_engine, expire_on_commit=False)
    app.include_router(auth_router)
    app.include_router(users_router, dependencies=[Depends(require_admin)])
    app.include_router(model_router, dependencies=[Depends(require_admin)])

    with TestClient(app) as test_client:
        yield test_client

    await read_engine.dispose()
    await auth_engine.dispose()
    await registry_engine.dispose()


def _create_and_login(client: TestClient, *, username: str, password: str, role: str) -> str:
    """Creates a user directly via the admin API using a bootstrap admin
    token, then logs in as the new user and returns their own token —
    exercises create + login together rather than minting tokens by
    hand, so these tests are also implicitly proving those two paths
    work every time they set up a fixture."""
    admin_token = _bootstrap_admin(client)
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201, response.text
    login = client.post("/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


_BOOTSTRAP_ADMIN_PASSWORD = "bootstrap-admin-password-123"


def _bootstrap_admin(client: TestClient) -> str:
    """The very first admin can't be created via POST /users (nothing
    can call it yet — that's the actual point of create_user.py existing
    as a host-only script, see its own docstring). Tests stand in for
    that script by inserting directly via the repository. Always
    checks-then-creates (not "once per session") because the `client`
    fixture TRUNCATEs `users` before every single test — a flag
    remembered across tests would go stale the moment the row it points
    at gets wiped by the next test's own setup.

    Uses its own throwaway engine via asyncio.run(), not
    client.app.state.auth_session_factory: TestClient runs the ASGI app
    in its own anyio portal thread with its own event loop, separate
    from whatever loop this synchronous test function is called from —
    reusing the app's engine here (created on the portal's loop) from a
    different one raises "Future attached to a different loop" the
    moment asyncpg tries to use it. asyncio.run() gives this its own
    fully self-contained loop, used and torn down within this one call,
    which sidesteps the mismatch entirely rather than fixing it."""
    import asyncio

    from app.auth.repository import create_user
    from app.auth.security import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def _create_if_missing() -> None:
        engine = create_async_engine(os.environ["AUTH_SERVICE_DATABASE_URL"])
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                existing = await session.execute(
                    text("SELECT 1 FROM users WHERE username = 'bootstrap-admin'")
                )
                if existing.scalar_one_or_none() is None:
                    await create_user(
                        session,
                        username="bootstrap-admin",
                        password_hash=hash_password(_BOOTSTRAP_ADMIN_PASSWORD),
                        role="admin",
                    )
        finally:
            await engine.dispose()

    asyncio.run(_create_if_missing())

    response = client.post(
        "/auth/login", json={"username": "bootstrap-admin", "password": _BOOTSTRAP_ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_admin_creates_a_user(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    response = client.post(
        "/users",
        json={"username": "checkout-member", "password": "a-decent-password-1", "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "checkout-member"
    assert body["role"] == "member"
    assert body["disabled"] is False


def test_duplicate_username_rejected(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    body = {"username": "dup-user", "password": "a-decent-password-1", "role": "member"}
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = client.post("/users", json=body, headers=headers)
    assert first.status_code == 201
    second = client.post("/users", json=body, headers=headers)
    assert second.status_code == 409


def test_weak_password_rejected(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    response = client.post(
        "/users",
        json={"username": "weak-pw-user", "password": "short", "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422


def test_member_gets_403_from_get_users(client: TestClient) -> None:
    member_token = _create_and_login(
        client, username="plain-member", password="a-decent-password-1", role="member"
    )
    response = client.get("/users", headers={"Authorization": f"Bearer {member_token}"})
    assert response.status_code == 403


def test_member_gets_403_from_the_model_router(client: TestClient) -> None:
    """The acceptance criterion this whole file is really about: a
    member's token is rejected the same way (403, admin required) from
    a *different* router that also moved onto require_admin, not just
    from /users itself."""
    member_token = _create_and_login(
        client, username="registry-blocked-member", password="a-decent-password-1", role="member"
    )
    # POST /model/components since Phase 30 — the /services alias this
    # test was first written against is gone, and the gate it proves
    # moved with the router that replaced it.
    response = client.post(
        "/model/components",
        json={"name": "blocked-service"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 403


def test_member_sees_incidents_router_shape_but_not_admin_routes(client: TestClient) -> None:
    """/incidents isn't mounted in this test app (see module docstring —
    this file's scope is auth/users + the cross-router 403 above), but a
    member's own token must still work for self-service endpoints."""
    member_token = _create_and_login(
        client, username="self-service-member", password="a-decent-password-1", role="member"
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {member_token}"})
    assert response.status_code == 200
    assert response.json()["role"] == "member"


def test_disabled_user_rejected_at_login(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    create = client.post(
        "/users",
        json={"username": "soon-disabled", "password": "a-decent-password-1", "role": "member"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_id = create.json()["id"]

    patch = client.patch(
        f"/users/{user_id}",
        json={"disabled": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch.status_code == 200
    assert patch.json()["disabled"] is True

    login = client.post(
        "/auth/login", json={"username": "soon-disabled", "password": "a-decent-password-1"}
    )
    assert login.status_code == 401


def test_admin_deletes_user_is_a_soft_delete(client: TestClient) -> None:
    admin_token = _bootstrap_admin(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    create = client.post(
        "/users",
        json={"username": "to-be-deleted", "password": "a-decent-password-1", "role": "member"},
        headers=headers,
    )
    user_id = create.json()["id"]

    delete = client.delete(f"/users/{user_id}", headers=headers)
    assert delete.status_code == 204

    listing = client.get("/users", headers=headers).json()["items"]
    deleted_entry = next(u for u in listing if u["id"] == user_id)
    assert deleted_entry["disabled"] is True


def test_self_service_password_change(client: TestClient) -> None:
    token = _create_and_login(
        client, username="password-changer", password="original-password-1", role="member"
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/auth/change-password",
        json={"current_password": "original-password-1", "new_password": "brand-new-password-1"},
        headers=headers,
    )
    assert response.status_code == 204

    old_login = client.post(
        "/auth/login", json={"username": "password-changer", "password": "original-password-1"}
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login", json={"username": "password-changer", "password": "brand-new-password-1"}
    )
    assert new_login.status_code == 200


def test_change_password_rejects_wrong_current_password(client: TestClient) -> None:
    token = _create_and_login(
        client, username="wrong-current-pw", password="original-password-1", role="member"
    )
    response = client.post(
        "/auth/change-password",
        json={"current_password": "not-the-real-password", "new_password": "brand-new-password-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_login_rate_limited_after_10_failures_per_minute(client: TestClient) -> None:
    for _ in range(10):
        response = client.post(
            "/auth/login", json={"username": "nonexistent-user", "password": "wrong"}
        )
        assert response.status_code == 401
    eleventh = client.post(
        "/auth/login", json={"username": "nonexistent-user", "password": "wrong"}
    )
    assert eleventh.status_code == 429
