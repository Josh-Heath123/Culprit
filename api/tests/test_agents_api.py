"""The agent routes (Phase 33 part 2), against a real database under the
real roles: agent-admin, agent-registrar, agent-gateway, api-reader, and
probe-writer and investigation-writer for what an agent stores.

Every agent request here is signed exactly as the binary signs one
(app/agents/signing.py, held to the shared fixture), with a key generated
for the test. Agent ids are unique per test rather than truncated between
tests: `agent_audit_log` refuses TRUNCATE, which is the point of it.
"""

import base64
import hashlib
import importlib
import json
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from app.agents import signing
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
# Built, never hand-formatted (scripts/tests/test_subject_construction.py).
EDGE = build("connection", from_component="a", to_component="b")
GENESIS = "0" * 64
RECORDED = Path(__file__).parent / "data" / "investigations"


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
) -> AsyncIterator[TestClient]:
    for variable, role, password in (
        ("AGENT_ADMIN_DATABASE_URL", "agent-admin", "AGENT_ADMIN_DB_PASSWORD"),
        ("AGENT_REGISTRAR_DATABASE_URL", "agent-registrar", "AGENT_REGISTRAR_DB_PASSWORD"),
        ("AGENT_GATEWAY_DATABASE_URL", "agent-gateway", "AGENT_GATEWAY_DB_PASSWORD"),
        ("PROBE_WRITER_DATABASE_URL", "probe-writer", "PROBE_WRITER_DB_PASSWORD"),
        (
            "INVESTIGATION_WRITER_DATABASE_URL",
            "investigation-writer",
            "INVESTIGATION_WRITER_DB_PASSWORD",
        ),
        (
            "VERIFICATION_WRITER_DATABASE_URL",
            "verification-writer",
            "VERIFICATION_WRITER_DB_PASSWORD",
        ),
    ):
        os.environ[variable] = role_database_url(role, password)
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    from app.agents import config as agents_config
    from app.facts import dependencies as facts_dependencies

    importlib.reload(agents_config)
    importlib.reload(facts_dependencies)
    from app.agents import dependencies as agents_dependencies

    importlib.reload(agents_dependencies)
    from app.agents import router as agents_router
    from app.investigations import router as investigations_router
    from app.readings import router as readings_router
    from app.verifications import router as verifications_router

    routers = (agents_router, investigations_router, readings_router, verifications_router)
    for module in routers:
        importlib.reload(module)

    from app.auth.dependencies import require_admin, require_auth
    from app.auth.security import AuthenticatedUser
    from app.errors import install as install_error_handlers

    engines = {
        "agent_admin_session_factory": create_async_engine(agents_config.AGENT_ADMIN_DATABASE_URL),
        "agent_registrar_session_factory": create_async_engine(
            agents_config.AGENT_REGISTRAR_DATABASE_URL
        ),
        "agent_gateway_session_factory": create_async_engine(
            agents_config.AGENT_GATEWAY_DATABASE_URL
        ),
        "probe_writer_session_factory": create_async_engine(
            os.environ["PROBE_WRITER_DATABASE_URL"]
        ),
        "investigation_writer_session_factory": create_async_engine(
            os.environ["INVESTIGATION_WRITER_DATABASE_URL"]
        ),
        "verification_writer_session_factory": create_async_engine(
            os.environ["VERIFICATION_WRITER_DATABASE_URL"]
        ),
        "session_factory": create_async_engine(
            role_database_url("api-reader", "API_READER_PASSWORD")
        ),
    }
    app = FastAPI()
    for name, engine in engines.items():
        setattr(app.state, name, async_sessionmaker(engine, expire_on_commit=False))
    install_error_handlers(app)
    for module in routers:
        app.include_router(module.router)
    admin = AuthenticatedUser(id=uuid.uuid4(), username="test-admin", role="admin")
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[require_auth] = lambda: admin

    with TestClient(app) as test_client:
        yield test_client

    for engine in engines.values():
        await engine.dispose()


# ---- an agent, as the binary is one --------------------------------------------------


class Agent:
    def __init__(self, client: TestClient, grants: dict[str, list[str]] | None = None):
        self.client = client
        self.id = "agent-" + secrets.token_hex(4)
        self.key = Ed25519PrivateKey.generate()
        self.grants = grants if grants is not None else {"production": ["net.tcp.connect"]}
        self.seq, self.last = 0, GENESIS

    @property
    def public_key(self) -> str:
        raw = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def registration(self, code: str) -> dict[str, Any]:
        return {
            "pairing_code": code,
            "agent_id": self.id,
            "public_key": self.public_key,
            "grants": self.grants,
        }

    def headers(self, method: str, path: str, body: bytes, **override: Any) -> dict[str, str]:
        request = signing.SignedRequest(
            method=method,
            path=path,
            body=body,
            timestamp=override.get("timestamp", int(time.time())),
            nonce=override.get("nonce", secrets.token_hex(16)),
            agent_id=self.id,
        )
        signature = base64.b64encode(self.key.sign(signing.canonical(request))).decode()
        return {
            signing.HEADER_AGENT: self.id,
            signing.HEADER_TIMESTAMP: str(request.timestamp),
            signing.HEADER_NONCE: request.nonce,
            signing.HEADER_SIGNATURE: signature,
            "Content-Type": "application/json",
        }

    def send(self, method: str, path: str, payload: Any = None, **override: Any):
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = self.headers(method, path, body, **override)
        return self.client.request(method, path, content=body, headers=headers)

    def audit_line(self, kind: str = "probe", **fields: Any) -> str:
        """An entry exactly as `agent.AuditLog.Append` writes one: Go's
        field order, compact JSON, the hash over the line with it empty."""
        entry: dict[str, Any] = {
            "seq": self.seq + 1,
            "time": "2026-11-06T10:00:00Z",
            "agent_id": self.id,
            "task_id": fields.get("task_id", "task-1"),
            "kind": kind,
            "environment": "production",
        }
        if kind == "probe":
            entry |= {"probe_id": "probe.net.tcp_connect", "target": EDGE}
        entry["grants"] = fields.get("grants", ["net.tcp.connect"])
        entry |= {"verdict": "pass"} if kind == "probe" else {"outcome": "completed"}
        entry["prev"] = self.last
        entry["hash"] = ""
        body = json.dumps(entry, separators=(",", ":"))
        digest = hashlib.sha256((self.last + "\n" + body).encode()).hexdigest()
        line = body[: -len('"hash":""}')] + f'"hash":"{digest}"' + "}"
        self.seq, self.last = entry["seq"], digest
        return line


def pairing_code(client: TestClient) -> str:
    response = client.post("/agents/pairing-codes")
    assert response.status_code == 201, response.text
    return response.json()["code"]


def paired(client: TestClient, grants: dict[str, list[str]] | None = None) -> Agent:
    agent = Agent(client, grants)
    response = client.post("/agents/register", json=agent.registration(pairing_code(client)))
    assert response.status_code == 201, response.text
    return agent


def reading(agent_id: str) -> dict[str, Any]:
    recorded = json.loads((RECORDED / "auth-audience.json").read_text("utf-8"))
    return recorded["readings"][0]["reading"] | {"agent_id": agent_id}


# ---- pairing ---------------------------------------------------------------------------


def test_a_pairing_code_works_once(client: TestClient) -> None:
    code = pairing_code(client)
    first, second = Agent(client), Agent(client)
    assert client.post("/agents/register", json=first.registration(code)).status_code == 201
    refused = client.post("/agents/register", json=second.registration(code))
    assert refused.status_code == 401
    assert "not valid" in refused.text


@pytest.mark.asyncio
async def test_an_expired_pairing_code_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    code = pairing_code(client)
    from app.agents.service import code_hash

    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE agent_pairing_codes SET expires_at = now() - interval '1 second' "
                "WHERE code_hash = :h"
            ),
            {"h": code_hash(code)},
        )
    assert client.post("/agents/register", json=Agent(client).registration(code)).status_code == 401


@pytest.mark.asyncio
async def test_a_pairing_code_is_stored_hashed(client: TestClient, db_engine: AsyncEngine) -> None:
    code = pairing_code(client)
    async with db_engine.connect() as conn:
        stored = (
            (await conn.execute(text("SELECT code_hash FROM agent_pairing_codes"))).scalars().all()
        )
    assert code not in stored
    assert all(len(value) == 64 for value in stored)


@pytest.mark.parametrize(
    "grants",
    [{"production": ["net.*"]}, {"production": ["all"]}, {"production": ["net.tcp.conect"]}],
)
def test_registration_refuses_a_wildcard_all_or_unknown_grant(client: TestClient, grants) -> None:
    agent = Agent(client, grants)
    response = client.post("/agents/register", json=agent.registration(pairing_code(client)))
    assert response.status_code == 422


def test_registration_never_takes_a_private_key(client: TestClient) -> None:
    agent = Agent(client)
    body = agent.registration(pairing_code(client)) | {"private_key": "x"}
    assert client.post("/agents/register", json=body).status_code == 422


# ---- allowances ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "grants,why",
    [
        (["net.dns.resolve"], "not reported"),
        (["net.*"], "wildcard"),
        (["all"], "all"),
    ],
)
def test_an_allowance_beyond_what_the_agent_reports_is_refused(
    client: TestClient, grants: list[str], why: str
) -> None:
    agent = paired(client)
    response = client.patch(
        f"/agents/{agent.id}/grants", json={"environment": "production", "grants": grants}
    )
    assert response.status_code == 422, why


def test_a_new_agents_allowance_is_empty(client: TestClient) -> None:
    agent = paired(client)
    listed = {item["id"]: item for item in client.get("/agents").json()["items"]}
    assert listed[agent.id]["allowances"] == {}
    task = client.post(
        f"/agents/{agent.id}/tasks",
        json={
            "environment": "production",
            "kind": "probe",
            "probe": {"probe_id": "probe.net.tcp_connect", "target": EDGE},
        },
    )
    assert task.status_code == 201
    claimed = agent.send("POST", "/agents/me/tasks/claim")
    assert claimed.status_code == 200
    assert claimed.json()["allowance"] == []


def _task(client: TestClient, agent: Agent) -> str:
    response = client.post(
        f"/agents/{agent.id}/tasks",
        json={
            "environment": "production",
            "kind": "probe",
            "probe": {
                "probe_id": "probe.net.tcp_connect",
                "target": EDGE,
                "inputs": {"host": "b", "port": 1},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_removing_a_grant_from_an_allowance_takes_effect_on_the_next_task(
    client: TestClient,
) -> None:
    agent = paired(client)
    allow = {"environment": "production", "grants": ["net.tcp.connect"]}
    assert client.patch(f"/agents/{agent.id}/grants", json=allow).status_code == 200
    _task(client, agent)
    assert agent.send("POST", "/agents/me/tasks/claim").json()["allowance"] == ["net.tcp.connect"]

    allow["grants"] = []
    assert client.patch(f"/agents/{agent.id}/grants", json=allow).status_code == 200
    _task(client, agent)
    assert agent.send("POST", "/agents/me/tasks/claim").json()["allowance"] == []


def test_an_agent_claims_only_its_own_tasks_and_each_once(client: TestClient) -> None:
    mine, theirs = paired(client), paired(client)
    task = _task(client, theirs)
    assert mine.send("POST", "/agents/me/tasks/claim").status_code == 204
    assert theirs.send("POST", "/agents/me/tasks/claim").json()["id"] == task
    assert theirs.send("POST", "/agents/me/tasks/claim").status_code == 204


def test_a_result_is_recorded_once_and_only_by_its_agent(client: TestClient) -> None:
    agent, other = paired(client), paired(client)
    task = _task(client, agent)
    agent.send("POST", "/agents/me/tasks/claim")
    result = {"outcome": "refused", "reason": "net.tcp.connect is not granted", "readings": 1}
    assert other.send("POST", f"/agents/me/tasks/{task}/result", result).status_code == 404
    assert agent.send("POST", f"/agents/me/tasks/{task}/result", result).status_code == 204
    assert agent.send("POST", f"/agents/me/tasks/{task}/result", result).status_code == 404
    stored = client.get(f"/agents/{agent.id}/tasks/{task}").json()
    assert stored["outcome"] == "refused" and stored["allowance"] == []


# ---- the signature -----------------------------------------------------------------------


def test_revoking_an_agent_refuses_its_very_next_request(client: TestClient) -> None:
    agent = paired(client)
    assert agent.send("POST", "/agents/me/tasks/claim").status_code == 204
    assert client.post(f"/agents/{agent.id}/revoke").status_code == 204
    refused = agent.send("POST", "/agents/me/tasks/claim")
    assert refused.status_code == 401
    assert refused.json()["detail"] == "request refused"


def test_a_replayed_request_is_refused(client: TestClient) -> None:
    agent = paired(client)
    headers = agent.headers("POST", "/agents/me/tasks/claim", b"")
    assert client.post("/agents/me/tasks/claim", content=b"", headers=headers).status_code == 204
    assert client.post("/agents/me/tasks/claim", content=b"", headers=headers).status_code == 401


def test_a_stale_request_is_refused(client: TestClient) -> None:
    agent = paired(client)
    stale = int(time.time()) - signing.MAX_SKEW_SECONDS - 5
    assert agent.send("POST", "/agents/me/tasks/claim", timestamp=stale).status_code == 401


def test_a_tampered_body_or_path_is_refused_and_the_answer_does_not_say_why(
    client: TestClient,
) -> None:
    agent = paired(client)
    signed = agent.headers("POST", "/agents/me/audit", b'{"entries":["x"]}')
    tampered = client.post("/agents/me/audit", content=b'{"entries":["y"]}', headers=signed)
    moved_headers = agent.headers("POST", "/agents/me/audit", b"")
    moved = client.post("/agents/me/tasks/claim", content=b"", headers=moved_headers)
    for response in (tampered, moved):
        assert response.status_code == 401
        assert response.json() == {"detail": "request refused"}


def test_the_wrong_key_is_refused(client: TestClient) -> None:
    agent = paired(client)
    agent.key = Ed25519PrivateKey.generate()
    assert agent.send("POST", "/agents/me/tasks/claim").status_code == 401


# ---- readings and investigations, under whose credential ---------------------------------


def test_post_readings_takes_an_agents_credential_and_nothing_else(client: TestClient) -> None:
    agent = paired(client)
    payload = {"readings": [reading(agent.id)]}
    by_token = client.post(
        "/readings", json=payload, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert by_token.status_code == 401
    assert client.post("/readings", json=payload).status_code == 401
    assert agent.send("POST", "/readings", payload).status_code == 201


def test_a_reading_naming_another_agent_is_refused(client: TestClient) -> None:
    agent = paired(client)
    payload = {"readings": [reading(agent.id), reading("someone-else")]}
    assert agent.send("POST", "/readings", payload).status_code == 403


@pytest.mark.asyncio
async def test_an_investigation_records_who_stored_it(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    async with db_engine.begin() as conn:
        # verifications (Phase 34) cascade from investigations, and refuse
        # TRUNCATE to every role: test setup lifts that, as the owner, and
        # restores it at once.
        await conn.execute(text("ALTER TABLE verifications DISABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations DISABLE TRIGGER USER"))
        await conn.execute(text("TRUNCATE investigations, verifications, narrations CASCADE"))
        await conn.execute(text("ALTER TABLE verifications ENABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations ENABLE TRIGGER USER"))
    agent = paired(client)
    by_token = json.loads((RECORDED / "network-partition.json").read_text("utf-8"))
    response = client.post(
        "/investigations", json=by_token, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert response.status_code == 201, response.text

    by_agent = json.loads((RECORDED / "auth-audience.json").read_text("utf-8"))
    for held in by_agent["readings"]:
        held["reading"]["agent_id"] = agent.id
    assert agent.send("POST", "/investigations", by_agent).status_code == 201

    listed = {
        item["id"]: item["submitted_by"] for item in client.get("/investigations").json()["items"]
    }
    assert listed[by_token["id"]] == "project-token"
    assert listed[by_agent["id"]] == f"agent:{agent.id}"


def test_an_agent_cannot_store_another_agents_readings_as_an_investigation(
    client: TestClient,
) -> None:
    agent = paired(client)
    payload = json.loads((RECORDED / "config.json").read_text("utf-8"))
    payload["id"] = "inv-" + secrets.token_hex(8)
    assert agent.send("POST", "/investigations", payload).status_code == 403


# ---- the audit log -------------------------------------------------------------------------


def test_an_agents_audit_chain_is_extended_and_read_back(client: TestClient) -> None:
    agent = paired(client)
    assert agent.send("GET", "/agents/me/audit/head").json() == {"seq": 0, "hash": GENESIS}
    lines = [agent.audit_line(), agent.audit_line(), agent.audit_line("task")]
    response = agent.send("POST", "/agents/me/audit", {"entries": lines})
    assert response.status_code == 200, response.text
    assert response.json() == {"seq": 3, "hash": agent.last}
    stored = client.get(f"/agents/{agent.id}/audit").json()["items"]
    assert [row["seq"] for row in stored] == [1, 2, 3]
    assert [row["kind"] for row in stored] == ["probe", "probe", "task"]


def test_an_entry_that_does_not_extend_the_stored_chain_is_refused(client: TestClient) -> None:
    agent = paired(client)
    first = agent.audit_line()
    agent.audit_line()  # skipped: never sent
    third = agent.audit_line()
    assert agent.send("POST", "/agents/me/audit", {"entries": [first]}).status_code == 200
    refused = agent.send("POST", "/agents/me/audit", {"entries": [third]})
    assert refused.status_code == 409
    assert refused.json()["detail"]["seq"] == 1
    # Sent again, the same entry is no longer an extension either.
    assert agent.send("POST", "/agents/me/audit", {"entries": [first]}).status_code == 409


def test_an_edited_entry_or_another_agents_is_refused(client: TestClient) -> None:
    agent, other = paired(client), paired(client)
    edited = agent.audit_line().replace('"verdict":"pass"', '"verdict":"fail"')
    assert agent.send("POST", "/agents/me/audit", {"entries": [edited]}).status_code == 422
    foreign = other.audit_line()
    assert agent.send("POST", "/agents/me/audit", {"entries": [foreign]}).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE agent_audit_log SET verdict = 'fail'",
        "DELETE FROM agent_audit_log",
        "TRUNCATE agent_audit_log",
    ],
)
async def test_no_role_the_owner_included_can_rewrite_the_audit_log(
    client: TestClient, db_engine: AsyncEngine, role_database_url, statement: str
) -> None:
    agent = paired(client)
    assert (
        agent.send("POST", "/agents/me/audit", {"entries": [agent.audit_line()]}).status_code == 200
    )
    # The owner (the superuser the migrations ran as): the triggers refuse it.
    with pytest.raises(DBAPIError):
        async with db_engine.begin() as conn:
            await conn.execute(text(statement))
    # The gateway, which appends: it has no such privilege at all.
    gateway = create_async_engine(role_database_url("agent-gateway", "AGENT_GATEWAY_DB_PASSWORD"))
    try:
        with pytest.raises(DBAPIError):
            async with gateway.begin() as conn:
                await conn.execute(text(statement))
    finally:
        await gateway.dispose()
    async with db_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM agent_audit_log WHERE agent_id = :a"), {"a": agent.id}
            )
        ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_the_database_refuses_an_entry_that_skips_ahead(
    db_engine: AsyncEngine, client: TestClient
) -> None:
    agent = paired(client)
    with pytest.raises(DBAPIError):
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_audit_log (agent_id, seq, prev, hash, kind, task_id, entry) "
                    "VALUES (:a, 2, :g, :h, 'task', 't', '{}')"
                ),
                {"a": agent.id, "g": GENESIS, "h": "c" * 64},
            )


def test_now_is_not_a_secret() -> None:
    # A guard against the test file's own clock helper drifting from UTC.
    assert datetime.now(UTC).tzinfo is UTC


@pytest.mark.asyncio
async def test_a_nonce_outlives_every_moment_its_request_could_still_be_fresh(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """A request stamped at the edge of future skew is fresh until
    2 * MAX_SKEW after it arrived. Its nonce must still be held then: a
    cleanup that dropped it after 2 * MAX_SKEW of `seen_at` left a replay
    window (the Phase 33 part 2 invariant audit)."""
    agent = paired(client)
    future = int(time.time()) + signing.MAX_SKEW_SECONDS - 10
    headers = agent.headers("POST", "/agents/me/tasks/claim", b"", timestamp=future)
    assert client.post("/agents/me/tasks/claim", content=b"", headers=headers).status_code == 204
    # Age the nonce just past the old cleanup line, then let a request run
    # the cleanup.
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE agent_nonces SET seen_at = now() - make_interval(secs => :age) "
                "WHERE nonce = :n"
            ),
            {"age": 2 * signing.MAX_SKEW_SECONDS + 1, "n": headers[signing.HEADER_NONCE]},
        )
    assert agent.send("POST", "/agents/me/tasks/claim").status_code == 204
    replay = client.post("/agents/me/tasks/claim", content=b"", headers=headers)
    assert replay.status_code == 401


# ---- the signature comes before the body (Phase 33 part 3, carried in) ---------------


_SIGNED = {
    "app.agents.dependencies.require_agent",
    "app.agents.dependencies.require_project_token_or_agent",
}


def _signs(dependant) -> bool:
    """Whether a route's dependency tree asks for an agent's signature. By
    qualified name, not identity: the `client` fixture reloads
    app.agents.dependencies, after which the function objects differ."""
    call = dependant.call
    if f"{getattr(call, '__module__', '')}.{getattr(call, '__qualname__', '')}" in _SIGNED:
        return True
    return any(_signs(child) for child in dependant.dependencies)


def _signed_routes() -> list[str]:
    """Every route the real application serves under an agent's signature,
    read from its dependency tree rather than listed here, so a signed route
    added later is covered without anyone remembering this test."""
    from app.main import app
    from tests.test_route_credentials import _routes

    routes = sorted(
        f"{method} {route.path}"
        for route in _routes(app.routes)
        if _signs(route.dependant)
        for method in sorted((route.methods or set()) - {"HEAD"})
    )
    assert len(routes) >= 6, f"only {routes} found: the walk is missing signed routes"
    return routes


#: Bodies a caller might send that cannot be parsed into anything: not JSON
#: at all, JSON of the wrong shape, and a body far from any schema.
_UNPARSEABLE = [b"{not json", b'{"readings": 7, "entries": 7, "id": 7}', b"[1, 2, 3]"]


def test_every_signed_route_is_covered() -> None:
    routes = _signed_routes()
    assert {
        "POST /readings",
        "POST /investigations",
        "POST /agents/me/audit",
        "POST /agents/me/tasks/{task_id}/result",
        "POST /investigations/{investigation_id}/verifications",
    } <= set(routes), routes


@pytest.mark.parametrize("body", _UNPARSEABLE, ids=["not-json", "wrong-shape", "array"])
def test_an_unsigned_or_badly_signed_request_is_refused_before_its_body_is_parsed(
    client: TestClient, body: bytes
) -> None:
    """On every signed route: no signature, a signature over other bytes,
    and a well-formed signature from an agent nobody paired are each a 401 —
    the same one — whatever the body holds. A 422 here would mean the body
    was parsed for a caller nobody had authenticated, and would tell that
    caller about the schema."""
    agent = paired(client)
    stranger = Agent(client)  # a key, but never registered
    from tests.test_route_credentials import _routes

    served = {
        f"{m} {r.path}" for r in _routes(cast(FastAPI, client.app).routes) for m in r.methods or ()
    }
    for route in _signed_routes():
        method, template = route.split(" ", 1)
        assert route in served, f"{route} is not mounted in this test's app"
        path = template.replace("{task_id}", "task-unknown").replace(
            "{investigation_id}", "inv-0000000000000000"
        )
        attempts = {
            "unsigned": {"Content-Type": "application/json"},
            "signed over other bytes": agent.headers(method, path, b'{"other": "body"}'),
            "unregistered agent": stranger.headers(method, path, body),
        }
        for why, headers in attempts.items():
            response = client.request(method, path, content=body, headers=headers)
            assert response.status_code == 401, (
                f"{route}, {why}: {response.status_code} {response.text}"
            )
            # The unsigned POST /investigations is a project-token request
            # without the token; everything else is one agent refusal.
            assert response.json()["detail"] in ("request refused", "missing bearer token"), (
                f"{route}, {why}: the refusal says more than that it was refused: {response.text}"
            )


@pytest.mark.parametrize("body", _UNPARSEABLE, ids=["not-json", "wrong-shape", "array"])
def test_a_correctly_signed_request_with_a_bad_body_is_still_a_422(
    client: TestClient, body: bytes
) -> None:
    """The other half: once the caller is known, a body that does not parse
    is still told so — the fix moves the parse, it does not drop it."""
    agent = paired(client)
    for route in ("POST /readings", "POST /agents/me/audit", "POST /investigations"):
        method, path = route.split(" ", 1)
        response = client.request(
            method, path, content=body, headers=agent.headers(method, path, body)
        )
        assert response.status_code == 422, f"{route}: {response.status_code} {response.text}"


# ---- when an agent last made a signed request (Phase 33 part 3) ----------------------


def _listed(client: TestClient, agent: Agent) -> dict[str, Any]:
    return {item["id"]: item for item in client.get("/agents").json()["items"]}[agent.id]


@pytest.mark.asyncio
async def test_the_last_signed_request_is_listed_and_survives_nonce_cleanup(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    agent = paired(client)
    assert _listed(client, agent)["last_request_at"] is None, "pairing is not a signed request"

    assert agent.send("POST", "/agents/me/tasks/claim").status_code == 204
    first = _listed(client, agent)["last_request_at"]
    assert first is not None

    # A refused request — signed over other bytes — moves nothing.
    bad = agent.headers("POST", "/agents/me/tasks/claim", b"other")
    assert client.post("/agents/me/tasks/claim", content=b"", headers=bad).status_code == 401
    assert _listed(client, agent)["last_request_at"] == first

    # Age every nonce this agent has spent far past retention, then let a
    # second agent's request run the cleanup: this agent's newest nonce is
    # kept, so its last request is still known; older ones of its are gone.
    assert agent.send("POST", "/agents/me/tasks/claim").status_code == 204
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE agent_nonces SET seen_at = seen_at - interval '1 day' WHERE agent_id = :a"
            ),
            {"a": agent.id},
        )
    other = paired(client)
    assert other.send("POST", "/agents/me/tasks/claim").status_code == 204
    async with db_engine.connect() as conn:
        kept = (
            await conn.execute(
                text("SELECT count(*) FROM agent_nonces WHERE agent_id = :a"), {"a": agent.id}
            )
        ).scalar_one()
    assert kept == 1, f"{kept} nonces kept for an agent idle a day: want exactly its newest"
    listed = _listed(client, agent)["last_request_at"]
    assert listed is not None
    age = datetime.now(UTC) - datetime.fromisoformat(listed)
    assert age.total_seconds() > 23 * 3600, f"last request {listed} is not the aged one"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO agent_nonces (agent_id, nonce, seen_at) VALUES ('x', 'y', now())",
        "DELETE FROM agent_nonces",
        "UPDATE agent_nonces SET nonce = 'z'",
        "SELECT nonce FROM agent_nonces",
        "SELECT * FROM agent_nonces",
    ],
)
async def test_api_reader_reads_nonces_and_writes_none(role_database_url, statement: str) -> None:
    """Q19 (Phase 34 part 2): api-reader reads the two columns the agents
    screen shows — agent_id and seen_at — and is refused the nonce itself,
    and every write."""
    reader = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    try:
        async with reader.connect() as conn:
            await conn.execute(text("SELECT agent_id, seen_at FROM agent_nonces LIMIT 1"))
        with pytest.raises(DBAPIError, match="permission denied"):
            async with reader.begin() as conn:
                await conn.execute(text(statement))
    finally:
        await reader.dispose()


# ---- verification (Phase 34 part 2) -------------------------------------------------------


async def _fresh(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE verifications DISABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations DISABLE TRIGGER USER"))
        await conn.execute(text("TRUNCATE investigations, verifications, narrations CASCADE"))
        await conn.execute(text("ALTER TABLE verifications ENABLE TRIGGER USER"))
        await conn.execute(text("ALTER TABLE narrations ENABLE TRIGGER USER"))


def _verification_by(agent: Agent, investigation: dict[str, Any]) -> dict[str, Any]:
    from tests.test_verifications_api import verification_of

    verification = verification_of(investigation)
    for rerun in verification["reran"]:
        for run in rerun["runs"]:
            run["agent_id"] = agent.id
    return verification


@pytest.mark.asyncio
async def test_an_agent_posts_the_verification_it_measured_and_is_recorded(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    await _fresh(db_engine)
    agent = paired(client)
    investigation = json.loads((RECORDED / "auth-audience.json").read_text("utf-8"))
    for held in investigation["readings"]:
        held["reading"]["agent_id"] = agent.id
    assert agent.send("POST", "/investigations", investigation).status_code == 201

    verification = _verification_by(agent, investigation)
    path = f"/investigations/{investigation['id']}/verifications"
    response = agent.send("POST", path, {"source": "planted", "verification": verification})
    assert response.status_code == 201, response.text
    listed = client.get(path).json()["items"]
    assert [item["submitted_by"] for item in listed] == [f"agent:{agent.id}"]

    # Runs that name another agent are not this agent's to post.
    other = _verification_by(agent, investigation)
    other["id"] = "ver-00000000000000aa"
    other["reran"][0]["runs"][0]["agent_id"] = "someone-else"
    refused = agent.send("POST", path, {"source": "planted", "verification": other})
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_a_verify_task_names_an_investigation_in_its_environment(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    await _fresh(db_engine)
    investigation = json.loads((RECORDED / "auth-audience.json").read_text("utf-8"))
    from culprit_model.subjects import build

    token_key = build("config", component="order-service", key="INVENTORY_TOKEN")
    stored = client.post(
        "/investigations", json=investigation, headers={"Authorization": f"Bearer {PROJECT_TOKEN}"}
    )
    assert stored.status_code == 201, stored.text
    agent = paired(client, {investigation["environment"]: ["net.tcp.connect"]})
    verify = {
        "investigation_id": investigation["id"],
        "changes": [{"kind": "config", "subject": token_key}],
        "source": "planted",
    }

    def task(**body: Any):
        payload = {"environment": investigation["environment"], "kind": "verify"} | body
        return client.post(f"/agents/{agent.id}/tasks", json=payload)

    created = task(verify=verify)
    assert created.status_code == 201, created.text
    claimed = agent.send("POST", "/agents/me/tasks/claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["kind"] == "verify"
    assert claimed.json()["verify"] == verify

    unknown = verify | {"investigation_id": "inv-00000000000000ff"}
    assert task(verify=unknown).status_code == 404
    elsewhere = client.post(
        f"/agents/{agent.id}/tasks",
        json={"environment": "somewhere-else", "kind": "verify", "verify": verify},
    )
    assert elsewhere.status_code == 422
    assert task().status_code == 422  # a verify task with nothing to verify
    assert task(verify=verify | {"source": "guess"}).status_code == 422  # source is said
    bad_change = verify | {"changes": [{"kind": "commit", "ref": "main"}]}
    assert task(verify=bad_change).status_code == 422

    # The words `culprit verify --change` takes, read here with subjects
    # built by subjects.build(): the dashboard formats no subject. (A
    # config key's words are its subject's text.)
    words = verify | {"changes": [token_key, "action: restarted it"]}
    assert task(verify=words).status_code == 201
    assert agent.send("POST", "/agents/me/tasks/claim").json()["verify"]["changes"] == [
        {"kind": "config", "subject": token_key},
        {"kind": "action", "description": "restarted it"},
    ]
    # An action's words are redacted before the task is stored (invariant 11).
    leaked = "postgresql://svc:hunter2-not-real@db.internal:5432/app"
    redacted = task(verify=verify | {"changes": [f"action: rotated {leaked}"]})
    assert redacted.status_code == 201, redacted.text
    async with db_engine.connect() as conn:
        spec = (
            await conn.execute(
                text("SELECT spec::text FROM agent_tasks WHERE id = :id"),
                {"id": redacted.json()["id"]},
            )
        ).scalar_one()
    assert "hunter2-not-real" not in spec
    for wrong in ("restart:order-service", "commit:main", "action:   "):
        assert task(verify=verify | {"changes": [wrong]}).status_code == 422, wrong
