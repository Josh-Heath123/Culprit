"""The narration job (Phase 35 part 2), against a real Postgres.

Each attempt is one call, with the investigation's evidence and nothing
else, and ends in one row with its final status: complete, refused with
what it named, or failed with a reason that carries nothing the provider
said. Three attempts, then none. With no provider, nothing at all.

Most tests use a scripted provider; two run the real `ollama` provider
against scripts/narrator_stub.py, the stub CI uses, so the HTTP code is
exercised too. Schema by `metadata.create_all`, as test_link_job.py does:
the role and append-only rules are the migration's, and api/tests/
test_narrations_api.py holds them against a migrated database.
"""

import asyncio
import contextlib
import json
import logging
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from app.db import metadata
from app.narrate import prompts, tables
from app.narrate.config import NarratorConfig
from app.narrate.job import MAX_ATTEMPTS, due, narrate_investigations, narrate_one
from app.narrate.providers import AnthropicProvider, OllamaProvider, ProviderError
from culprit_model.investigations import Investigation
from culprit_model.narration import MAX_PROSE, evidence
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parents[2]
RECORDED = ROOT / "api" / "tests" / "data" / "investigations" / "auth-audience.json"
STUB = ROOT / "scripts" / "narrator_stub.py"
SECRETS = ("sk-ant-api03-", "hunter2", "postgresql://")

pytestmark = pytest.mark.asyncio


class Scripted:
    """A provider with scripted replies: a string is returned, an exception
    raised, a float slept for. Records every call."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, float):
            await asyncio.sleep(reply)
            return "too late"
        return str(reply)


def recorded(description: str | None = None) -> dict[str, Any]:
    investigation = json.loads(RECORDED.read_text("utf-8"))
    if description is not None:
        investigation["symptom"]["description"] = description
    return investigation


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("timescale/timescaledb-ha:pg16", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture
async def engine(postgres_container: PostgresContainer) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(postgres_container.get_connection_url())
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(metadata.create_all)
        for table in (
            tables.narrations,
            tables.fault_edge_readings,
            tables.fault_edges,
            tables.hypotheses,
            tables.investigation_readings,
            tables.investigations,
        ):
            await conn.execute(delete(table))
    yield eng
    await eng.dispose()


async def store(engine: AsyncEngine, record: dict[str, Any], ingested: datetime) -> Investigation:
    """The five tables' rows, as api/app/investigations/service.store writes them."""
    investigation = Investigation.model_validate(record)
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.investigations).values(
                id=investigation.id,
                opened_at=investigation.opened_at,
                closed_at=investigation.closed_at,
                environment=investigation.environment,
                symptom=investigation.symptom.model_dump(mode="json"),
                diagnosis=investigation.diagnosis.model_dump(mode="json")
                if investigation.diagnosis
                else None,
                ingested_at=ingested,
            )
        )
        for held in investigation.readings:
            await conn.execute(
                insert(tables.investigation_readings).values(
                    investigation_id=investigation.id,
                    id=held.id,
                    reading=held.reading.model_dump(mode="json"),
                )
            )
        for h in investigation.hypotheses:
            await conn.execute(
                insert(tables.hypotheses).values(
                    investigation_id=investigation.id,
                    id=h.id,
                    kind=h.kind,
                    subject=h.subject,
                    status=h.status.value,
                    reason=h.reason,
                    readings=list(h.readings),
                )
            )
        for index, edge in enumerate(investigation.fault_tree):
            await conn.execute(
                insert(tables.fault_edges).values(
                    investigation_id=investigation.id,
                    id=index,
                    from_subject=edge.from_subject,
                    to_subject=edge.to_subject,
                    relation=edge.relation.value,
                )
            )
            for reading_id in edge.established_by:
                await conn.execute(
                    insert(tables.fault_edge_readings).values(
                        investigation_id=investigation.id, edge_id=index, reading_id=reading_id
                    )
                )
    return investigation


async def narrations(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        query = select(tables.narrations).order_by(tables.narrations.c.attempt)
        return [dict(row) for row in (await conn.execute(query)).mappings()]


def ctx(engine: AsyncEngine | None, provider: object, retry: float = 0.0) -> dict[str, Any]:
    config = NarratorConfig(provider="ollama", model="m", ollama_url="x", retry_seconds=retry)
    return {"narrator_engine": engine, "narrator_provider": provider, "narrator_config": config}


async def test_a_faithful_reply_is_stored_complete_after_one_call_built_from_the_record(
    engine: AsyncEngine,
) -> None:
    investigation = await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted("The order service's token carries the wrong audience [2]. Fix it [3].")

    assert await narrate_investigations(ctx(engine, provider)) == {"narrated": 1}

    # One call; its input is the constant system prompt and the evidence
    # built from the stored record — the same as built from the file.
    assert provider.calls == [
        (prompts.SYSTEM, prompts.render(evidence(Investigation.model_validate(recorded()))))
    ]
    assert provider.calls[0][1] == prompts.render(evidence(investigation))
    (row,) = await narrations(engine)
    assert row["status"] == "complete" and row["attempt"] == 1
    assert row["prose"].startswith("The order service's token")
    assert row["reason"] is None and row["named"] is None
    assert (row["provider"], row["model"]) == ("scripted", "scripted-1")

    # Complete stands: no further call, however many ticks.
    for _ in range(3):
        await narrate_investigations(ctx(engine, provider))
    assert len(provider.calls) == 1


async def test_a_reply_naming_what_is_not_there_is_refused_and_its_prose_not_kept(
    engine: AsyncEngine,
) -> None:
    await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted("The billing-service broke, see probe.net.tls_validity [2].")

    await narrate_investigations(ctx(engine, provider))

    (row,) = await narrations(engine)
    assert row["status"] == "refused"
    assert row["prose"] is None
    assert row["named"] == ["probe.net.tls_validity", "billing-service"]


@pytest.mark.parametrize(
    "reply, reason",
    [
        (ProviderError("scripted answered HTTP 503"), "scripted answered HTTP 503"),
        ("   ", "scripted answered with nothing"),
        (5.0, "scripted did not answer in time"),
        (
            RuntimeError("boom " + "sk-ant-api03-" + "Q" * 40),
            "scripted failed (RuntimeError)",
        ),
        ("x" * 4001, "the reply from scripted was longer than 4000 characters"),
    ],
    ids=["provider-error", "empty", "timeout", "exception", "too-long"],
)
async def test_a_failure_is_stored_with_a_reason_and_nothing_the_provider_said(
    engine: AsyncEngine, reply: object, reason: str
) -> None:
    investigation = await store(engine, recorded(), datetime.now(UTC))
    status = await narrate_one(engine, Scripted(reply), investigation.id, timeout_seconds=0.5)

    assert status == "failed"
    (row,) = await narrations(engine)
    assert row["reason"] == reason
    assert row["prose"] is None and row["named"] is None


async def test_three_attempts_then_no_fourth_call(engine: AsyncEngine) -> None:
    await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted(ProviderError("scripted answered HTTP 500"))

    for _ in range(MAX_ATTEMPTS + 3):
        await narrate_investigations(ctx(engine, provider, retry=0.0))

    assert len(provider.calls) == MAX_ATTEMPTS
    rows = await narrations(engine)
    assert [row["attempt"] for row in rows] == [1, 2, 3]
    assert {row["status"] for row in rows} == {"failed"}


async def test_overlapping_ticks_call_the_provider_once(engine: AsyncEngine) -> None:
    """A slow provider and a cron every 15 seconds: ticks overlap. The
    attempt is claimed before the call, so only one tick calls."""
    await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted(0.5)  # sleeps half a second, then answers

    await asyncio.gather(*(narrate_investigations(ctx(engine, provider)) for _ in range(4)))

    assert len(provider.calls) == 1
    assert [row["attempt"] for row in await narrations(engine)] == [1]


async def test_a_database_error_mid_attempt_releases_the_claim(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database error aborts the transaction the claim was taken on. The
    error must surface as itself, and the advisory lock must not outlive it
    on a pooled connection."""
    from app.narrate import job

    investigation = await store(engine, recorded(), datetime.now(UTC))

    async def broken_load(conn, investigation_id):
        await conn.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(job, "load", broken_load)
    with pytest.raises(DBAPIError, match="division by zero"):
        await narrate_one(engine, Scripted("x"), investigation.id, timeout_seconds=1.0)

    async with engine.connect() as conn:
        held = (
            await conn.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"))
        ).scalar_one()
    assert held == 0


async def test_a_failed_attempt_waits_before_the_next(engine: AsyncEngine) -> None:
    await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted(ProviderError("scripted answered HTTP 500"))

    for _ in range(3):
        await narrate_investigations(ctx(engine, provider, retry=3600.0))

    assert len(provider.calls) == 1


async def test_an_attempt_whose_row_is_refused_is_stored_failed_and_counted(
    engine: AsyncEngine,
) -> None:
    """The call was made, so it is counted: a row the database will not take
    is stored as failed, and the next tick inside the retry interval makes
    no second call. (Before the close-out: no row, and a second call.)"""
    investigation = await store(engine, recorded(), datetime.now(UTC))
    provider = Scripted("The order service's token carries the wrong audience [2]. Fix it [3].")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE narrations ADD CONSTRAINT ck_test_no_complete "
                "CHECK (status <> 'complete')"
            )
        )
    try:
        for _ in range(2):
            # A tick the insert fails in must not raise either; were it to,
            # the stored row below is what is missing.
            with contextlib.suppress(DBAPIError):
                await narrate_investigations(ctx(engine, provider, retry=3600.0))
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE narrations DROP CONSTRAINT ck_test_no_complete"))

    assert len(provider.calls) == 1
    (row,) = await narrations(engine)
    assert (row["investigation_id"], row["attempt"]) == (investigation.id, 1)
    assert row["status"] == "failed"
    assert row["reason"] == "the narration could not be stored"
    assert row["prose"] is None and row["named"] is None


async def test_when_no_row_can_be_stored_the_error_carries_none_of_the_row(
    engine: AsyncEngine,
) -> None:
    """Both the attempt's row and its failed row refused: the error raised
    names a constraint, and chains nothing that renders the failing row."""
    from app.narrate.job import NarrationNotStored

    investigation = await store(engine, recorded(), datetime.now(UTC))
    prose = "The order service's token carries the wrong audience [2]. Fix it [3]."
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE narrations ADD CONSTRAINT ck_test_nothing CHECK (attempt > 99)")
        )
    try:
        with pytest.raises(NarrationNotStored) as raised:
            await narrate_one(engine, Scripted(prose), investigation.id, 1.0)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE narrations DROP CONSTRAINT ck_test_nothing"))

    assert str(raised.value) == "ck_test_nothing"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    shown = "".join(traceback.format_exception(raised.value))
    assert "wrong audience" not in shown and "Failing row" not in shown
    async with engine.connect() as conn:
        held = (
            await conn.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"))
        ).scalar_one()
    assert held == 0


async def test_ticks_that_read_due_before_either_claims_make_one_attempt(
    engine: AsyncEngine,
) -> None:
    """Two ticks both see the investigation due, then each takes the claim
    in turn. The second reads the retry interval again under the claim and
    finds the first's attempt inside it."""
    investigation = await store(engine, recorded(), datetime.now(UTC))
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.narrations).values(
                id="nar-" + "0" * 16,
                investigation_id=investigation.id,
                attempt=1,
                status="failed",
                provider="scripted",
                model="scripted-1",
                reason="scripted answered HTTP 500",
                narrated_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
    retry = timedelta(hours=1)
    async with engine.connect() as conn:
        first = await due(conn, retry)
    async with engine.connect() as conn:
        second = await due(conn, retry)
    assert first == second == [investigation.id]
    provider = Scripted(ProviderError("scripted answered HTTP 500"))

    for _ in (first, second):
        await narrate_one(engine, provider, investigation.id, 1.0, retry)

    assert len(provider.calls) == 1
    assert [row["attempt"] for row in await narrations(engine)] == [1, 2]


async def test_with_no_provider_nothing_is_read_or_called() -> None:
    # No engine at all: the job must return before it would need one.
    assert await narrate_investigations(ctx(None, None)) == {"narrated": 0}


# ---- the real ollama provider, against the stub CI uses ---------------------


@pytest.fixture(scope="module")
def stub() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-I", str(STUB), "--host", "127.0.0.1", "--port", str(port)]
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while True:
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1).close()
            break
        except OSError:
            if time.monotonic() > deadline:
                process.kill()
                raise
            time.sleep(0.1)
    yield url
    process.kill()
    process.wait()


def calls(url: str) -> dict[str, int]:
    with urllib.request.urlopen(url + "/calls", timeout=5) as response:
        return json.loads(response.read())


def ollama(url: str) -> OllamaProvider:
    return OllamaProvider(NarratorConfig(provider="ollama", model="stub", ollama_url=url))


async def test_ollama_against_the_stub_narrates_faithfully(engine: AsyncEngine, stub: str) -> None:
    investigation = await store(engine, recorded(), datetime.now(UTC))
    before = calls(stub)["total"]

    assert await narrate_one(engine, ollama(stub), investigation.id, 10.0) == "complete"
    assert calls(stub)["total"] == before + 1


async def test_a_provider_error_leaves_no_trace_of_what_it_said(
    engine: AsyncEngine, stub: str, caplog: pytest.LogCaptureFixture
) -> None:
    investigation = await store(engine, recorded("narrator-stub:fail"), datetime.now(UTC))
    caplog.set_level(logging.DEBUG)

    assert await narrate_one(engine, ollama(stub), investigation.id, 10.0) == "failed"

    (row,) = await narrations(engine)
    assert row["reason"] == "ollama answered HTTP 500"
    stored = json.dumps(row, default=str)
    for secret in SECRETS:
        assert secret not in stored
        assert secret not in caplog.text


# ---- the anthropic provider's request, with no network --------------------------


def anthropic(handler) -> AnthropicProvider:
    config = NarratorConfig(provider="anthropic", model="a-model", api_key="test-key-not-real")
    return AnthropicProvider(config, transport=httpx.MockTransport(handler))


async def test_anthropic_sends_one_message_no_tools_and_no_stream() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "It failed [1]."},
                ],
            },
        )

    reply = await anthropic(handler).complete("the system prompt", "the evidence")

    assert reply == "It failed [1]."
    (request,) = seen
    assert request.method == "POST" and str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "test-key-not-real"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert set(body) == {"model", "max_tokens", "system", "messages"}
    assert body["system"] == "the system prompt"
    assert body["messages"] == [{"role": "user", "content": "the evidence"}]
    # No more tokens than a narration may hold characters.
    assert 0 < body["max_tokens"] <= MAX_PROSE


@pytest.mark.parametrize(
    "response, reason",
    [
        (
            httpx.Response(529, json={"error": {"message": "sk-ant-api03-" + "Q" * 40}}),
            "anthropic answered HTTP 529",
        ),
        (
            httpx.Response(200, json={"stop_reason": "refusal", "content": []}),
            "anthropic declined to answer (refusal)",
        ),
        (
            httpx.Response(200, json={"stop_reason": "max_tokens", "content": []}),
            "anthropic's reply was cut off at its token limit",
        ),
        (
            httpx.Response(200, text="<html>not json</html>"),
            "anthropic answered with something that is not JSON",
        ),
        (
            httpx.Response(200, json={"content": "not a list"}),
            "anthropic answered in a shape it does not use",
        ),
    ],
    ids=["http-error", "refusal", "max-tokens", "not-json", "wrong-shape"],
)
async def test_anthropic_failures_are_closed_vocabulary(
    response: httpx.Response, reason: str
) -> None:
    with pytest.raises(ProviderError) as raised:
        await anthropic(lambda request: response).complete("s", "u")
    assert raised.value.reason == reason


# ---- the ollama provider's request, with no network ----------------------------


async def test_ollama_asks_for_no_more_tokens_than_a_narration_may_hold() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok [1]."}})

    config = NarratorConfig(provider="ollama", model="m", ollama_url="http://ollama.test")
    provider = OllamaProvider(config, transport=httpx.MockTransport(handler))

    assert await provider.complete("s", "u") == "ok [1]."
    (request,) = seen
    body = json.loads(request.content)
    assert 0 < body["options"]["num_predict"] <= MAX_PROSE
    assert body["stream"] is False and "tools" not in body


async def test_an_ollama_reply_cut_off_at_its_limit_fails() -> None:
    config = NarratorConfig(provider="ollama", model="m", ollama_url="http://ollama.test")
    reply = {"done_reason": "length", "message": {"role": "assistant", "content": "It fa"}}
    provider = OllamaProvider(
        config, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
    )
    with pytest.raises(ProviderError) as raised:
        await provider.complete("s", "u")
    assert raised.value.reason == "ollama's reply was cut off at its token limit"
