"""HTTP-level tests for the system model (Phase 27).

Same shape as `test_registry_api.py`, and for the same reasons: a minimal
app with the router mounted behind the real `require_admin`, driven
against a real migrated Postgres container rather than mocks, with every
`app.*` import deferred into the fixture (app.model.router transitively
imports app.ingest_gateway.auth via app.registry.keys, which builds a DB
engine at import time).

Two of the phase's four acceptance criteria are checked here by
execution:

  * **`culprit.yaml` round-trips: apply, export, diff is empty.**
    Split across three tests, because `dump_manifest` emits a *canonical*
    form (defaults omitted, connections ordered) and so a byte comparison
    against a hand-written file measures formatting rather than the
    model. `test_manifest_round_trips_with_nothing_lost_or_invented`
    checks that no component, edge, kind or criticality changed;
    `test_export_is_a_fixed_point` checks the byte-level half — an export
    re-exports identically and re-applying it reports no changes;
    `test_component_order_survives_the_round_trip` checks that ordering
    is preserved rather than alphabetised. See docs/LIMITS.md.
  * **Given a symptom component, the model returns the ordered set of
    upstream connections on its request path.**
    `test_request_path_is_ordered_from_the_symptom` drives it through
    `GET /model/graph?symptom=`.

The third (an existing deployment upgrades without data loss) lives in
`test_model_migration.py`, which needs a pre-migration database. The
fourth (the dashboard renders components and typed connections) is a
frontend concern; what is checkable from here is that the API actually
serves the kind and criticality the dashboard needs, which
`test_connections_expose_their_kind_and_criticality` asserts.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import yaml
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

#: A system Culprit did not author (Phase 27 field 13) — a frontend, two
#: services, a database, a cache and an external API, with four
#: connection kinds and a background edge. Nothing about it resembles the
#: demo triangle, which is the point: the loader and the graph must work
#: on a shape this repository never produced.
STOREFRONT_YAML = """
version: 1
components:
  - name: storefront-web
    kind: frontend
    display_name: Storefront
    connections:
      - to: checkout-api
        kind: http
        criticality: on_request_path
  - name: checkout-api
    kind: service
    display_name: Checkout API
    labels:
      team: payments
    connections:
      - to: checkout-db
        kind: sql
        criticality: on_request_path
      - to: pricing-cache
        kind: cache
        criticality: on_request_path
      - to: stripe
        kind: http
        criticality: on_request_path
      - to: receipts-worker
        kind: message
        criticality: background
  - name: checkout-db
    kind: database
  - name: pricing-cache
    kind: cache
  - name: stripe
    kind: external_api
  - name: receipts-worker
    kind: job
"""


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see module docstring
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    async with db_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE components, connections, api_keys, observed_service_edges CASCADE")
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


def _apply(client: TestClient, manifest: str, *, prune: bool = False) -> dict:
    response = client.post("/model/apply", json={"manifest": manifest, "prune": prune})
    assert response.status_code == 200, response.text
    return response.json()


def _export(client: TestClient) -> str:
    response = client.get("/model/export")
    assert response.status_code == 200, response.text
    return response.json()["manifest"]


# --- components and connections ---------------------------------------


def test_create_component_returns_a_one_time_key(client: TestClient) -> None:
    response = client.post(
        "/model/components", json={"name": "orders-svc", "kind": "database"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["component"]["name"] == "orders-svc"
    assert body["component"]["kind"] == "database"
    assert body["api_key"].startswith("clp_live_")


def test_component_responses_never_leak_key_material(client: TestClient) -> None:
    """Inherited from the Phase 14 registry test, which exists because a
    schema-only review would not catch a `keys[].key_hash` field being
    added back in later."""
    client.post("/model/components", json={"name": "orders-svc"})
    body = client.get("/model/components").text
    assert "key_hash" not in body
    assert "clp_live_" not in body


def test_an_unknown_component_kind_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/model/components", json={"name": "orders-svc", "kind": "microfrontend"}
    )
    assert response.status_code == 422


def test_a_connection_to_an_unknown_component_is_refused(client: TestClient) -> None:
    client.post("/model/components", json={"name": "orders-svc"})
    response = client.post(
        "/model/connections",
        json={"from_component": "orders-svc", "to_component": "ghost", "kind": "http"},
    )
    assert response.status_code == 400
    assert "ghost" in response.json()["detail"]


def test_two_kinds_between_the_same_pair_are_both_allowed(client: TestClient) -> None:
    for name in ("orders-svc", "orders-db"):
        client.post("/model/components", json={"name": name})
    for kind in ("http", "sql"):
        response = client.post(
            "/model/connections",
            json={"from_component": "orders-svc", "to_component": "orders-db", "kind": kind},
        )
        assert response.status_code == 201, response.text

    # ...and the same kind twice is not.
    duplicate = client.post(
        "/model/connections",
        json={"from_component": "orders-svc", "to_component": "orders-db", "kind": "sql"},
    )
    assert duplicate.status_code == 409


def test_a_self_connection_is_refused(client: TestClient) -> None:
    client.post("/model/components", json={"name": "orders-svc"})
    response = client.post(
        "/model/connections",
        json={"from_component": "orders-svc", "to_component": "orders-svc"},
    )
    assert response.status_code == 400


def test_connections_expose_their_kind_and_criticality(client: TestClient) -> None:
    """What the dashboard needs to render typed connections at all."""
    _apply(client, STOREFRONT_YAML)
    items = client.get("/model/connections").json()["items"]
    by_pair = {(c["from_component"], c["to_component"]): c for c in items}

    assert by_pair[("checkout-api", "checkout-db")]["kind"] == "sql"
    assert by_pair[("checkout-api", "pricing-cache")]["kind"] == "cache"
    assert by_pair[("checkout-api", "receipts-worker")]["criticality"] == "background"
    assert by_pair[("storefront-web", "checkout-api")]["criticality"] == "on_request_path"
    # Field 17: contract_id stays null throughout Phase 27.
    assert all(c["contract_id"] is None for c in items)


# --- acceptance criterion 2: culprit.yaml round-trips -----------------


def _model_of(manifest: str) -> tuple[set, set]:
    """A manifest reduced to what it actually asserts about the system:
    the set of components and the set of typed, classified edges.

    Formatting, key order and omitted defaults are all deliberately
    discarded here — they are presentation, and comparing them would be
    testing pyyaml's dumper rather than whether the model survived.
    """
    parsed = yaml.safe_load(manifest)
    components = set()
    connections = set()
    for entry in parsed["components"]:
        components.add(
            (
                entry["name"],
                entry.get("kind", "service"),
                entry.get("display_name"),
                tuple(sorted((entry.get("labels") or {}).items())),
                tuple(sorted(entry.get("environments") or ())),
                tuple(sorted(entry.get("monitored_metrics") or ())),
            )
        )
        for connection in entry.get("connections") or ():
            connections.add(
                (
                    entry["name"],
                    connection["to"],
                    connection.get("kind", "http"),
                    connection.get("criticality", "unknown"),
                )
            )
    return components, connections


def test_manifest_round_trips_with_nothing_lost_or_invented(client: TestClient) -> None:
    """Acceptance criterion 2: apply, export, diff is empty.

    Checked on what the manifest *asserts*, because `dump_manifest`
    emits a canonical form — it omits fields left at their default and
    orders each component's connections. So a hand-written file that is
    not already canonical comes back reformatted, and a byte comparison
    would fail on `kind: http` having been dropped rather than on
    anything being wrong. The claim worth checking is that no component,
    no edge, no kind and no criticality was lost or invented, and that is
    what this asserts. The byte-level half of the criterion is
    `test_export_is_a_fixed_point` below. See docs/LIMITS.md.
    """
    _apply(client, STOREFRONT_YAML)
    assert _model_of(_export(client)) == _model_of(STOREFRONT_YAML)


def test_export_is_a_fixed_point(client: TestClient) -> None:
    """The byte-level half: an exported manifest re-exports identically,
    and re-applying it changes nothing.

    This is the part a single apply/export comparison would miss. A round
    trip that converges only on the second pass is not a round trip, and
    an `apply` that reports changes every time it runs makes its own
    output useless for review.
    """
    _apply(client, STOREFRONT_YAML)
    exported = _export(client)

    result = _apply(client, exported)
    assert result["components_created"] == []
    assert result["components_updated"] == []
    assert result["connections_created"] == []
    assert result["connections_updated"] == []
    assert result["connections_removed"] == []
    assert _export(client) == exported


def test_component_order_survives_the_round_trip(client: TestClient) -> None:
    """Ordering is part of the document, not an accident of iteration.

    `apply` records each component's position in the file as its
    `sort_order`, so an export hands back the author's own ordering
    rather than an alphabetised rearrangement of it — which is what makes
    a real `culprit.yaml` diff reviewable at all.
    """
    _apply(client, STOREFRONT_YAML)
    exported = yaml.safe_load(_export(client))
    original = yaml.safe_load(STOREFRONT_YAML)

    assert [c["name"] for c in exported["components"]] == [
        c["name"] for c in original["components"]
    ]


def test_apply_is_idempotent(client: TestClient) -> None:
    first = _apply(client, STOREFRONT_YAML)
    assert len(first["components_created"]) == 6
    assert len(first["connections_created"]) == 5

    second = _apply(client, STOREFRONT_YAML)
    assert second["components_created"] == []
    assert second["connections_created"] == []


def test_apply_removes_an_edge_the_manifest_dropped(client: TestClient) -> None:
    _apply(client, STOREFRONT_YAML)
    trimmed = STOREFRONT_YAML.replace(
        """      - to: pricing-cache
        kind: cache
        criticality: on_request_path
""",
        "",
    )
    result = _apply(client, trimmed)
    assert result["connections_removed"] == ["checkout-api -cache-> pricing-cache"]


def test_apply_leaves_an_accepted_suggestion_alone(client: TestClient) -> None:
    """A manifest is authoritative for the edges it declares, not for
    ones that came from somewhere else. An accepted Phase 19 suggestion
    is evidence a human acted on, and `apply` must not quietly destroy
    it."""
    _apply(client, STOREFRONT_YAML)
    inferred = client.post(
        "/model/connections",
        json={
            "from_component": "checkout-api",
            "to_component": "storefront-web",
            "kind": "http",
            "declared_by": "accepted_suggestion",
        },
    )
    assert inferred.status_code == 201, inferred.text

    _apply(client, STOREFRONT_YAML)
    pairs = {
        (c["from_component"], c["to_component"], c["declared_by"])
        for c in client.get("/model/connections").json()["items"]
    }
    assert ("checkout-api", "storefront-web", "accepted_suggestion") in pairs


# --- acceptance criterion 4: the request path -------------------------


def test_request_path_is_ordered_from_the_symptom(client: TestClient) -> None:
    _apply(client, STOREFRONT_YAML)
    body = client.get("/model/graph", params={"symptom": "checkout-api"}).json()

    assert body["symptom"] == "checkout-api"
    assert [
        (c["from_component"], c["to_component"], c["kind"]) for c in body["request_path"]
    ] == [
        # One hop, sorted within it. The background edge to
        # receipts-worker is absent — it is reachable, but a nightly job
        # is not on the path a failing request took.
        ("checkout-api", "checkout-db", "sql"),
        ("checkout-api", "pricing-cache", "cache"),
        ("checkout-api", "stripe", "http"),
    ]


def test_request_path_from_the_frontend_crosses_two_hops(client: TestClient) -> None:
    _apply(client, STOREFRONT_YAML)
    body = client.get("/model/graph", params={"symptom": "storefront-web"}).json()
    path = [(c["from_component"], c["to_component"]) for c in body["request_path"]]

    assert path[0] == ("storefront-web", "checkout-api")
    assert ("checkout-api", "stripe") in path
    assert ("checkout-api", "receipts-worker") not in path


def test_graph_without_a_symptom_returns_no_request_path(client: TestClient) -> None:
    _apply(client, STOREFRONT_YAML)
    body = client.get("/model/graph").json()
    assert body["symptom"] is None
    assert body["request_path"] == []
    assert len(body["components"]) == 6


def test_an_unknown_symptom_is_a_404_not_an_empty_path(client: TestClient) -> None:
    """An empty request path and "no such component" are different
    answers, and returning the former for the latter turns a typo into
    "nothing upstream could have caused this"."""
    _apply(client, STOREFRONT_YAML)
    response = client.get("/model/graph", params={"symptom": "checkout-apu"})
    assert response.status_code == 404


# --- field 12: no secrets in a culprit.yaml ---------------------------


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param(
            "version: 1\ncomponents:\n  - name: a\n    labels:\n      password: hunter2\n",
            id="a key that names a secret",
        ),
        pytest.param(
            "version: 1\ncomponents:\n  - name: a\n    labels:\n"
            "      dsn: postgresql://u:hunter2@db/orders\n",
            id="a DSN with inline credentials",
        ),
        pytest.param(
            "version: 1\ncomponents:\n  - name: a\n    labels:\n"
            "      note: AKIAIOSFODNN7EXAMPLE\n",
            id="an AWS access key id",
        ),
    ],
)
def test_a_manifest_carrying_a_credential_is_refused(
    client: TestClient, manifest: str
) -> None:
    response = client.post("/model/apply", json={"manifest": manifest, "prune": False})
    assert response.status_code == 400
    # The refusal must not echo the secret back into a log or a CI run.
    assert "hunter2" not in response.text
    assert "AKIAIOSFODNN7EXAMPLE" not in response.text


def test_a_manifest_referencing_an_undeclared_component_is_refused(
    client: TestClient,
) -> None:
    manifest = "version: 1\ncomponents:\n  - name: a\n    connections:\n      - to: b\n"
    response = client.post("/model/apply", json={"manifest": manifest, "prune": False})
    assert response.status_code == 400
    assert "not declared" in response.json()["detail"]


# --- regressions found by the Phase 27 invariant audit ----------------


def test_export_omits_edges_the_manifest_does_not_own(client: TestClient) -> None:
    """An accepted topology suggestion must not be laundered into the
    manifest.

    `_apply_connections` treats every edge in a manifest as
    `culprit_yaml`-owned and removes owned edges the file stops listing.
    So if `--export` wrote an accepted suggestion into the file, the
    documented workflow `apply_model --export > culprit.yaml` would
    silently transfer ownership, and the next apply that dropped the line
    would delete an edge a human had explicitly accepted — the exact
    thing `accept_topology_suggestion` promises will not happen.
    """
    _apply(client, STOREFRONT_YAML)
    client.post(
        "/model/connections",
        json={
            "from_component": "checkout-api",
            "to_component": "storefront-web",
            "kind": "http",
            "declared_by": "accepted_suggestion",
        },
    )

    exported = _export(client)
    assert "storefront-web" in exported  # it is still a component...
    # ...but the accepted edge is not one of checkout-api's connections.
    checkout = next(
        entry
        for entry in yaml.safe_load(exported)["components"]
        if entry["name"] == "checkout-api"
    )
    assert "storefront-web" not in {c["to"] for c in checkout.get("connections", [])}

    # And it survives a full round trip through the exported file.
    _apply(client, exported)
    pairs = {
        (c["from_component"], c["to_component"], c["declared_by"])
        for c in client.get("/model/connections").json()["items"]
    }
    assert ("checkout-api", "storefront-web", "accepted_suggestion") in pairs


def test_a_first_apply_does_not_report_a_component_as_created_and_updated(
    client: TestClient,
) -> None:
    """`sort_order` is set at creation, not in a second pass. Otherwise
    every new component appears in both lists, which makes the report
    unreadable exactly when it matters most."""
    result = _apply(client, STOREFRONT_YAML)
    assert len(result["components_created"]) == 6
    assert result["components_updated"] == []


def test_graph_excludes_disabled_components_and_their_edges(
    client: TestClient,
) -> None:
    """A disabled component is dropped from `components`, not merely from
    `request_path`. Returning it as a node while every traversal treats
    it as absent would hand a caller a graph it cannot draw."""
    _apply(client, STOREFRONT_YAML)
    stripe = next(
        c for c in client.get("/model/components").json()["items"] if c["name"] == "stripe"
    )
    client.patch(f"/model/components/{stripe['id']}", json={"disabled": True})

    body = client.get("/model/graph").json()
    assert "stripe" not in {c["name"] for c in body["components"]}
    assert "stripe" not in {c["to_component"] for c in body["connections"]}
    # ...but Settings still needs to see it, to offer an "Enable" button.
    assert "stripe" in {c["name"] for c in client.get("/model/components").json()["items"]}
