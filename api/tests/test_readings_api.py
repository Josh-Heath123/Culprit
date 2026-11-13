"""`POST /readings` (Phase 31), against a real database, under the real
roles: `probe-writer` for the write, `api-reader` for the read-back.

Since Phase 33 part 2 the endpoint takes an agent's signature and nothing
else, so every post here is signed by a test agent registered in the
fixture, and every reading names it (app/agents/dependencies.py).

`readings` had no grant on it at all until this phase — it was created in
Phase 26 and deliberately left unreachable. These tests are therefore as
much about what the new role *cannot* do as about the endpoint working:
`probe-writer` appends to the evidence log and cannot read a single row
of it back, which is the property that makes a leaked probe credential a
small problem rather than a disclosure of every measurement ever taken.
"""

import base64
import importlib
import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from culprit_model.subjects import build
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROJECT_TOKEN = "test-project-token-not-a-real-secret"
AGENT_ID = "readings-test-agent"
AGENT_KEY = Ed25519PrivateKey.generate()
# Built, never hand-formatted — scripts/tests/test_subject_construction.py
# holds tests to the same rule as application code.
EDGE = build("connection", from_component="orders-api", to_component="payments-api")


def _reading(**overrides) -> dict:
    reading = {
        "probe_id": "probe.edge.impedance",
        "probe_version": 1,
        "target": EDGE,
        "environment": "production",
        "verdict": "pass",
        "measured": {"metric": "http.server.duration", "deviation": 0.4, "samples": 120},
        "taken_at": datetime(2026, 9, 12, 10, 0, tzinfo=UTC).isoformat(),
        "agent_id": AGENT_ID,
        "grants_used": ["telemetry.metrics.read"],
    }
    reading.update(overrides)
    return reading


@pytest_asyncio.fixture
async def client(
    migrated_database_url: str,  # ordering dependency — see test_registry_api.py
    role_database_url,
    db_engine: AsyncEngine,
) -> AsyncIterator[TestClient]:
    public = AGENT_KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE readings"))
        # The test agent, registered as pairing would register it.
        await conn.execute(
            text(
                "WITH c AS (INSERT INTO agent_pairing_codes (code_hash, created_by, expires_at, "
                "used_at, used_by) VALUES (:h, 'test', now(), now(), :a) RETURNING id) "
                "INSERT INTO agents (id, public_key, reported_grants, pairing_code_id) "
                "SELECT :a, :k, '{}'::jsonb, c.id FROM c ON CONFLICT (id) DO NOTHING"
            ),
            {"h": secrets.token_hex(32), "a": AGENT_ID, "k": public},
        )

    os.environ["PROBE_WRITER_DATABASE_URL"] = role_database_url(
        "probe-writer", "PROBE_WRITER_DB_PASSWORD"
    )
    os.environ["CULPRIT_PROJECT_TOKEN"] = PROJECT_TOKEN

    from app.facts import dependencies as facts_dependencies
    from app.readings import config as readings_config

    importlib.reload(readings_config)
    importlib.reload(facts_dependencies)
    from app.readings import router as readings_router_module

    importlib.reload(readings_router_module)

    from app.auth.dependencies import require_auth
    from app.errors import install as install_error_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    writer = create_async_engine(readings_config.PROBE_WRITER_DATABASE_URL)
    gateway = create_async_engine(role_database_url("agent-gateway", "AGENT_GATEWAY_DB_PASSWORD"))
    app = FastAPI()
    app.state.probe_writer_session_factory = async_sessionmaker(writer, expire_on_commit=False)
    app.state.agent_gateway_session_factory = async_sessionmaker(gateway, expire_on_commit=False)
    install_error_handlers(app)
    app.include_router(readings_router_module.router)
    # A user session is require_auth's own concern and has its own tests;
    # here it only has to be *present* on the two /probes routes.
    app.dependency_overrides[require_auth] = lambda: {"sub": "tester", "role": "member"}

    with TestClient(app) as test_client:
        yield test_client
    await writer.dispose()
    await gateway.dispose()


def _signed(body: bytes) -> dict[str, str]:
    from app.agents import signing

    request = signing.SignedRequest(
        method="POST",
        path="/readings",
        body=body,
        timestamp=int(time.time()),
        nonce=secrets.token_hex(16),
        agent_id=AGENT_ID,
    )
    return {
        signing.HEADER_AGENT: AGENT_ID,
        signing.HEADER_TIMESTAMP: str(request.timestamp),
        signing.HEADER_NONCE: request.nonce,
        signing.HEADER_SIGNATURE: base64.b64encode(
            AGENT_KEY.sign(signing.canonical(request))
        ).decode(),
        "Content-Type": "application/json",
    }


def _post(client: TestClient, payload: dict, signed: bool = True, token: str | None = None):
    body = json.dumps(payload).encode()
    headers = _signed(body) if signed else {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/readings", content=body, headers=headers)


async def _count(db_engine: AsyncEngine) -> int:
    async with db_engine.begin() as conn:
        return int((await conn.execute(text("SELECT count(*) FROM readings"))).scalar_one())


@pytest.mark.asyncio
async def test_a_batch_of_readings_is_stored(client: TestClient, db_engine: AsyncEngine) -> None:
    later = (datetime(2026, 9, 12, 10, 0, tzinfo=UTC) + timedelta(seconds=5)).isoformat()
    response = _post(
        client,
        {"readings": [_reading(), _reading(verdict="fail", taken_at=later)]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["stored"] == 2
    assert body["duplicates"] == 0
    assert await _count(db_engine) == 2


@pytest.mark.asyncio
async def test_an_exact_duplicate_within_one_batch_is_collapsed(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """A retrying agent resubmits the same measurement; two rows would
    make one measurement look like two. A reading at a *different*
    instant is history, not a duplicate, and is kept."""
    later = (datetime(2026, 9, 12, 10, 0, tzinfo=UTC) + timedelta(seconds=5)).isoformat()
    response = _post(
        client,
        {"readings": [_reading(), _reading(), _reading(taken_at=later)]},
    )
    assert response.status_code == 201, response.text
    assert response.json() == {
        "stored": 2,
        "duplicates": 1,
        "stored_at": response.json()["stored_at"],
    }
    assert await _count(db_engine) == 2


def test_a_reading_without_an_agents_signature_is_refused(client: TestClient) -> None:
    """Phase 33 part 2: the project token, which this endpoint took until
    then, is refused like any other credential that is not an agent's."""
    payload = {"readings": [_reading()]}
    assert _post(client, payload, signed=False).status_code == 401
    assert _post(client, payload, signed=False, token=PROJECT_TOKEN).status_code == 401
    assert _post(client, payload, signed=False, token="wrong").status_code == 401


@pytest.mark.asyncio
async def test_an_unresolved_verdict_without_a_reason_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """The model's rule (§2.6), enforced before any application code sees
    the row: a probe that cannot say why it could not answer is a probe
    that guesses. The database says the same thing in a CHECK; this
    asserts the request never gets that far."""
    response = _post(client, {"readings": [_reading(verdict="inconclusive")]})
    assert response.status_code == 422
    assert await _count(db_engine) == 0


LATENCY_MEASURED = {
    "percentile": 95,
    "requests": 50,
    "planned": 50,
    "samples_us": [10_000] * 50,
    "timeouts": 0,
}
LATENCY_BUDGET = {"latency_p95_ms": 300}


def _latency(verdict: str, measured: dict | None = None) -> dict:
    return _reading(
        probe_id="probe.http.latency",
        target=build("http", component="inventory-service", method="GET", path="/ready"),
        verdict=verdict,
        measured=LATENCY_MEASURED if measured is None else measured,
        expected=LATENCY_BUDGET,
        reason="judged",
        grants_used=["net.http.outbound"],
    )


@pytest.mark.asyncio
async def test_a_latency_reading_whose_verdict_its_samples_do_not_give_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Phase 36: a latency reading carries its samples and its budget, so
    its verdict is a pure function of the reading. Fifty answers at 10 ms
    against a 300 ms p95 pass; a reading saying they fail is refused, and
    nothing is stored."""
    for wrong in ("fail", "inconclusive"):
        response = _post(client, {"readings": [_latency(wrong)]})
        assert response.status_code == 422, wrong
    assert await _count(db_engine) == 0

    response = _post(client, {"readings": [_latency("pass")]})
    assert response.status_code == 201, response.text
    assert await _count(db_engine) == 1


STATEMENT_MEASURED = {
    "reset_during_window": False,
    "statements": [{"queryid": "7", "calls": 5, "total_us": 260_000, "budget_ms": 50}],
}


@pytest.mark.asyncio
async def test_a_statement_reading_whose_verdict_its_integers_do_not_give_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Phase 37 part 2: a statement reading carries each statement's calls,
    total time and budget, so its verdict is re-judged from those integers.
    260 ms over 5 calls against 50 ms each is over; a reading saying pass or
    inconclusive is refused, and nothing is stored."""

    def statement(verdict: str) -> dict:
        return _reading(
            probe_id="probe.db.statement_budget",
            target=build("component", name="inventory-db"),
            verdict=verdict,
            measured=STATEMENT_MEASURED,
            expected={"database_budget_ms": 50},
            reason="judged",
            grants_used=["db.stats.read"],
        )

    for wrong in ("pass", "inconclusive"):
        response = _post(client, {"readings": [statement(wrong)]})
        assert response.status_code == 422, wrong
    assert await _count(db_engine) == 0

    response = _post(client, {"readings": [statement("fail")]})
    assert response.status_code == 201, response.text
    assert await _count(db_engine) == 1


@pytest.mark.asyncio
async def test_a_latency_reading_without_planned_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """Phase 37 part 1: `planned` is a required input of the rule (probe
    version 2). Without it a run cut short would be judged on its samples
    alone, so a reading that does not say is refused, whatever its verdict,
    and nothing is stored."""
    without = {key: value for key, value in LATENCY_MEASURED.items() if key != "planned"}
    for verdict in ("pass", "fail", "inconclusive"):
        response = _post(client, {"readings": [_latency(verdict, without)]})
        assert response.status_code == 422, verdict
    assert await _count(db_engine) == 0


@pytest.mark.asyncio
async def test_a_hand_formatted_target_is_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """`target` is a subject URI or it is nothing. A target that does not
    parse would silently never join to anything."""
    response = _post(client, {"readings": [_reading(target="orders-api to payments-api")]})
    assert response.status_code == 422
    assert await _count(db_engine) == 0


@pytest.mark.asyncio
async def test_a_422_does_not_echo_what_was_refused(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """app/errors.py, on this path. `measured` is agent-supplied and ends
    up in this API's access log if the validation error reflects it."""
    marker = "s3cret-looking-marker-value"
    response = _post(
        client,
        {"readings": [_reading(verdict="refused", measured={"note": marker})]},
    )
    assert response.status_code == 422
    assert marker not in response.text


@pytest.mark.asyncio
async def test_probe_writer_can_do_exactly_what_the_endpoint_needs(role_database_url) -> None:
    """A thirteenth role, not a third reuse (.claude/rules/database.md).

    Asserted both ways: INSERT on `readings` works, and everything else —
    including reading back what it just wrote — does not. The SELECT half
    is the one that matters: the endpoint's insert path is deliberately
    RETURNING-free so that this grant can stay absent.
    """
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(role_database_url("probe-writer", "PROBE_WRITER_DB_PASSWORD"))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO readings "
                    "(taken_at, probe_id, probe_version, target, environment, "
                    " verdict, agent_id) "
                    "VALUES (now(), 'probe.edge.impedance', 1, :target, "
                    "'production', 'pass', 'culprit-worker')"
                ),
                {"target": EDGE},
            )
        for statement in (
            "SELECT 1 FROM readings LIMIT 1",
            "DELETE FROM readings",
            "UPDATE readings SET verdict = 'fail'",
            # The other two planes, and the tables that are not evidence
            # at all. A probe credential lives wherever probes run, which
            # is closer to production than any other credential here.
            "SELECT 1 FROM configured_facts LIMIT 1",
            "SELECT 1 FROM intent_facts LIMIT 1",
            "SELECT 1 FROM captures LIMIT 1",
            "SELECT 1 FROM divergences LIMIT 1",
            "SELECT 1 FROM users LIMIT 1",
            "SELECT 1 FROM api_keys LIMIT 1",
            "SELECT 1 FROM components LIMIT 1",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_reader_reads_readings_and_writes_nothing(role_database_url) -> None:
    """The established reader pattern, asserted rather than assumed —
    every dashboard read runs under this role, and none of them may
    write."""
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(role_database_url("api-reader", "API_READER_PASSWORD"))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM readings LIMIT 1"))
        for statement in (
            "DELETE FROM readings",
            "UPDATE readings SET verdict = 'fail'",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_anomaly_detector_reads_connections_but_still_cannot_write_a_reading(
    role_database_url,
) -> None:
    """The worker's anomaly job needs `connections` to attribute a metric
    row to an edge (rule (b) in worker/app/anomaly/job.py). It does *not*
    get to write the reading it attributes — that goes through
    `probe-writer`, which is the whole reason the split exists."""
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        role_database_url("anomaly-detector", "ANOMALY_DETECTOR_DB_PASSWORD")
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM connections LIMIT 1"))
        for statement in (
            "SELECT 1 FROM readings LIMIT 1",
            "INSERT INTO connections (from_component_id, to_component_id, kind) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'http')",
        ):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_credential_posted_in_a_reading_is_not_what_gets_stored(
    client: TestClient, db_engine: AsyncEngine
) -> None:
    """`POST /readings` accepts readings from outside the CLI's guarantee.

    The CLI redacts before a Reading exists as a value, so its own output
    is safe by construction. This endpoint is reachable by a third-party
    probe, an older binary, or a hand-written payload, and what it accepts
    lands in a 90-day hypertable that `api-reader` can SELECT. Found by
    the Phase 31 invariant audit, which demonstrated the same class of
    leak through `culprit probe --format json`.

    Redacted rather than refused: `measured` legitimately carries a
    caller's URL, and rejecting the batch would lose every honest reading
    alongside the careless one.
    """
    leaky = _reading(
        verdict="fail",
        reason="no HTTP response from https://admin:hunter2@orders.internal/health",
        measured={
            "url": "https://admin:hunter2@orders.internal/health",
            "status": 503,
            "nested": {"dsn": "postgresql://admin:hunter2@db.internal:5432/orders"},
        },
    )
    response = _post(client, {"readings": [leaky]})
    assert response.status_code == 201, response.text

    async with db_engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT reason, measured::text AS measured FROM readings LIMIT 1")
            )
        ).one()

    assert "hunter2" not in row.reason, row.reason
    assert "hunter2" not in row.measured, row.measured
    # Redaction must not have eaten the measurement it was protecting.
    assert "503" in row.measured, row.measured
