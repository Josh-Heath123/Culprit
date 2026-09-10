"""HTTP-level tests for what `app/registry/` still owns — ingest API keys
and the Phase 19 topology-suggestion queue — plus the component CRUD
behaviour the Phase 14 registry tests first pinned down, all driven
through `/model/*` since Phase 30 removed the `/services` alias (field
6). Real FastAPI `TestClient`, real migrated Postgres container (see
api/tests/conftest.py), no mocks.

This file was the first real HTTP-level integration test in the
codebase, written against `/services`. What it tested was worth keeping;
the path it tested it through was not. Tests that only described the
alias's *translation* — `depends_on` flattened to http connections, a
legacy PATCH that must not delete a `sql` edge it could not see, a PATCH
that validated `depends_on` after writing — went with the alias, because
the thing they guarded no longer exists. Everything else moved.

Deliberately builds a minimal test app (the model router mounted
directly, behind the same `require_admin` dependency app/main.py uses)
instead of importing app.main's own `app` — app.main's lifespan also
stands up an arq/Redis connection pool for the root-cause-regeneration
endpoint, which has nothing to do with the model and would make every
test in this file depend on a Redis container too, for no benefit.

Every import from app.* below is deferred into the `client` fixture
rather than sitting at module level: app.model.router transitively
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
        await conn.execute(
            text(
                "TRUNCATE components, connections, api_keys, "
                "observed_service_edges CASCADE"
            )
        )
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
    from app.model.router import router as model_router
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    read_engine = create_async_engine(api_reader_url)
    write_engine = create_async_engine(registry_admin_url)
    auth_engine = create_async_engine(auth_service_url)

    app = FastAPI()
    app.state.session_factory = async_sessionmaker(read_engine, expire_on_commit=False)
    app.state.registry_session_factory = async_sessionmaker(write_engine, expire_on_commit=False)
    app.include_router(model_router, dependencies=[Depends(require_admin)])

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
    response = client.post("/model/components", json={"name": name, **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def _connect(client: TestClient, source: str, target: str, kind: str = "http") -> None:
    response = client.post(
        "/model/connections",
        json={"from_component": source, "to_component": target, "kind": kind},
    )
    assert response.status_code == 201, response.text


# --- Phase 30: the alias is gone, not merely unused -------------------


def test_the_services_alias_is_gone(client: TestClient) -> None:
    """Phase 30 field 6. A 404 — nothing answers at `/services` any more,
    so a script still written against it fails on its first request
    rather than half-working."""
    _create(client, "checkout-api")
    assert client.get("/services").status_code == 404
    assert client.post("/services", json={"name": "x"}).status_code == 404
    assert client.get("/services/topology/suggestions").status_code == 404


# --- components: the behaviour the Phase 14 registry pinned down ------


def test_create_returns_component_and_one_time_key(client: TestClient) -> None:
    body = _create(client, "checkout-api", display_name="Checkout API")
    assert body["component"]["name"] == "checkout-api"
    assert body["component"]["display_name"] == "Checkout API"
    assert body["component"]["disabled"] is False
    # The initial key is listed on the component — metadata only.
    assert len(body["component"]["keys"]) == 1
    assert body["component"]["keys"][0]["revoked"] is False
    assert body["component"]["keys"][0]["label"] == "initial"
    assert body["api_key"].startswith("clp_live_")


def test_duplicate_name_rejected(client: TestClient) -> None:
    _create(client, "checkout-api")
    response = client.post("/model/components", json={"name": "checkout-api"})
    assert response.status_code == 409


def test_invalid_name_rejected(client: TestClient) -> None:
    response = client.post("/model/components", json={"name": "Not Valid!"})
    assert response.status_code == 422


def test_list_includes_created_component_with_its_keys(client: TestClient) -> None:
    _create(client, "checkout-api")
    response = client.get("/model/components")
    assert response.status_code == 200
    items = {c["name"]: c for c in response.json()["items"]}
    assert "checkout-api" in items
    # The list, not only the detail, carries keys: Settings → Services
    # renders every component's keys from this one request.
    assert len(items["checkout-api"]["keys"]) == 1


def test_patch_updates_display_name_and_metrics(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["component"]

    response = client.patch(
        f"/model/components/{checkout['id']}",
        json={"display_name": "Checkout", "monitored_metrics": ["http.server.duration"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Checkout"
    assert body["monitored_metrics"] == ["http.server.duration"]


def test_patch_omitted_fields_are_left_alone(client: TestClient) -> None:
    checkout = _create(client, "checkout-api", display_name="Checkout")["component"]

    response = client.patch(f"/model/components/{checkout['id']}", json={"sort_order": 5})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Checkout"
    assert response.json()["sort_order"] == 5


def test_soft_delete_disables_but_keeps_the_component(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["component"]

    response = client.delete(f"/model/components/{checkout['id']}")
    assert response.status_code == 204

    get_response = client.get(f"/model/components/{checkout['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["disabled"] is True


def test_purge_hard_deletes_the_component(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["component"]

    response = client.delete(f"/model/components/{checkout['id']}?purge=true")
    assert response.status_code == 204

    assert client.get(f"/model/components/{checkout['id']}").status_code == 404


# --- ingest keys ------------------------------------------------------


def test_issue_and_revoke_key(client: TestClient) -> None:
    checkout = _create(client, "checkout-api")["component"]

    issue_response = client.post(
        f"/model/components/{checkout['id']}/keys", json={"label": "rotation"}
    )
    assert issue_response.status_code == 201
    issued = issue_response.json()
    assert issued["api_key"].startswith("clp_live_")
    assert issued["label"] == "rotation"

    revoke_response = client.delete(
        f"/model/components/{checkout['id']}/keys/{issued['key_id']}"
    )
    assert revoke_response.status_code == 204

    component = client.get(f"/model/components/{checkout['id']}").json()
    revoked_key = next(k for k in component["keys"] if k["id"] == issued["key_id"])
    assert revoked_key["revoked"] is True


def test_issuing_a_key_for_an_unknown_component_404s(client: TestClient) -> None:
    response = client.post(
        "/model/components/00000000-0000-0000-0000-000000000000/keys", json={"label": "x"}
    )
    assert response.status_code == 404


def test_a_key_cannot_be_revoked_through_another_components_path(
    client: TestClient,
) -> None:
    """`revoke_key` scopes the lookup to the component in the URL. Without
    that, knowing any key id would let a request under one component
    revoke another component's key."""
    checkout = _create(client, "checkout-api")["component"]
    inventory = _create(client, "inventory-api")["component"]
    checkout_key = checkout["keys"][0]["id"]

    response = client.delete(f"/model/components/{inventory['id']}/keys/{checkout_key}")
    assert response.status_code == 404

    after = client.get(f"/model/components/{checkout['id']}").json()
    assert after["keys"][0]["revoked"] is False


def test_no_key_material_ever_appears_in_a_response(client: TestClient) -> None:
    created = _create(client, "checkout-api")
    plaintext_key = created["api_key"]
    component_id = created["component"]["id"]
    second = client.post(f"/model/components/{component_id}/keys", json={"label": "second"})
    second_plaintext = second.json()["api_key"]

    list_response = client.get("/model/components")
    detail_response = client.get(f"/model/components/{component_id}")
    graph_response = client.get("/model/graph")

    for response in (list_response, detail_response, graph_response):
        # The concern this guards against is a field like `key_hash`
        # getting added back to ComponentOut/KeyOut later, not just the
        # value of a hash the tests happen to know — searching for the
        # field name itself, not a specific hash, is what catches that.
        # `/model/graph` is included because it returns ComponentOut too,
        # and so carries `keys` since Phase 30.
        assert "key_hash" not in response.text
        assert plaintext_key not in response.text
        assert second_plaintext not in response.text


# --- Phase 19: topology suggestions ---------------------------------------


async def _seed_edge(
    db_engine: AsyncEngine, from_service: str, to_service: str, observations: int = 1
) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO observed_service_edges (from_service, to_service, observations) "
                "VALUES (:f, :t, :o)"
            ),
            {"f": from_service, "t": to_service, "o": observations},
        )


async def test_suggestions_lists_observed_edge_flagged_unregistered(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    await _seed_edge(db_engine, "order-service", "inventory-service", observations=42)

    response = client.get("/model/topology/suggestions")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["from_service"] == "order-service"
    assert items[0]["to_service"] == "inventory-service"
    assert items[0]["observations"] == 42
    assert items[0]["from_service_registered"] is False
    assert items[0]["to_service_registered"] is False


async def test_suggestions_omits_an_already_declared_connection(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    _create(client, "order-service")
    _create(client, "inventory-service")
    _connect(client, "order-service", "inventory-service")
    await _seed_edge(db_engine, "order-service", "inventory-service")

    response = client.get("/model/topology/suggestions")
    assert response.json()["items"] == []


async def test_suggestions_omits_a_pair_joined_by_any_connection_kind(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """`_already_declared_pairs` counts every kind, not just http: if a
    `sql` connection already records that the two are joined,
    re-suggesting the pair asks the admin to declare what the model
    already knows."""
    _create(client, "order-service")
    _create(client, "orders-db")
    _connect(client, "order-service", "orders-db", kind="sql")
    await _seed_edge(db_engine, "order-service", "orders-db")

    response = client.get("/model/topology/suggestions")
    assert response.json()["items"] == []


async def test_suggestions_omits_dismissed_edge(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    await _seed_edge(db_engine, "order-service", "inventory-service")
    dismiss = client.post(
        "/model/topology/suggestions/dismiss",
        json={"from_service": "order-service", "to_service": "inventory-service"},
    )
    assert dismiss.status_code == 204

    response = client.get("/model/topology/suggestions")
    assert response.json()["items"] == []


async def test_suggestions_ordered_by_observations_descending(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    await _seed_edge(db_engine, "order-service", "inventory-service", observations=5)
    await _seed_edge(db_engine, "order-service", "payments-service", observations=50)

    response = client.get("/model/topology/suggestions")
    pairs = [(item["from_service"], item["to_service"]) for item in response.json()["items"]]
    assert pairs == [
        ("order-service", "payments-service"),
        ("order-service", "inventory-service"),
    ]


async def test_accept_creates_an_accepted_connection_and_removes_the_suggestion(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    _create(client, "order-service")
    _create(client, "inventory-service")
    await _seed_edge(db_engine, "order-service", "inventory-service")

    response = client.post(
        "/model/topology/suggestions/accept",
        json={"from_service": "order-service", "to_service": "inventory-service"},
    )
    assert response.status_code == 204

    connections = client.get("/model/connections").json()["items"]
    accepted = [
        c
        for c in connections
        if (c["from_component"], c["to_component"]) == ("order-service", "inventory-service")
    ]
    assert len(accepted) == 1
    assert accepted[0]["kind"] == "http"
    # The provenance the old surface could not express, and the reason
    # `apply_model` leaves this edge alone when a manifest omits it.
    assert accepted[0]["declared_by"] == "accepted_suggestion"

    assert client.get("/model/topology/suggestions").json()["items"] == []


async def test_accept_refuses_clearly_when_target_not_registered(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Known Trap 2 (docs/SELF_HOSTED_PLAN.md Phase 19): accepting an
    edge whose target isn't registered must refuse clearly, not silently
    half-register a component with no API key."""
    _create(client, "order-service")
    await _seed_edge(db_engine, "order-service", "inventory-service")

    response = client.post(
        "/model/topology/suggestions/accept",
        json={"from_service": "order-service", "to_service": "inventory-service"},
    )
    assert response.status_code == 400
    items = client.get("/model/components").json()["items"]
    # No half-registered inventory-service was created as a side effect.
    assert [c["name"] for c in items] == ["order-service"]
    assert client.get("/model/connections").json()["items"] == []


async def test_accept_unknown_edge_404s(client: TestClient) -> None:
    response = client.post(
        "/model/topology/suggestions/accept",
        json={"from_service": "ghost", "to_service": "phantom"},
    )
    assert response.status_code == 404


def test_dismiss_unknown_edge_404s(client: TestClient) -> None:
    response = client.post(
        "/model/topology/suggestions/dismiss",
        json={"from_service": "ghost", "to_service": "phantom"},
    )
    assert response.status_code == 404
