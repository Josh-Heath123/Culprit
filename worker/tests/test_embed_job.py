"""Unit tests for app.rag.embed_job.embed_postmortem (Phase 18).

No testcontainers here (worker/tests/ has no DB-container fixture at
all — every existing test in this directory is a pure unit test, per
CLAUDE.md) and no real Voyage call (worker/tests/test_rag_providers.py's
own docstring: "none of this needs a real API key" is the established
convention for anything touching an LLM/embedding client in this
project's test suite). Both the Voyage client and the DB engine are
faked here — there's no existing precedent in this codebase for mocking
either the Voyage client specifically or a raw SQLAlchemy Core
engine/connection, so this establishes that pattern rather than copying
one.

The fake engine tracks exactly the two operations embed_postmortem
performs (one SELECT to read `body`, one UPDATE to write a result) by
statement type, not by pretending to be a real database — good enough to
assert what this job actually writes, without needing Postgres at all.
"""

from typing import Any
from uuid import uuid4

import pytest
from app.rag.embed_job import embed_postmortem
from arq import Retry
from sqlalchemy import Select, Update
from voyageai.error import RateLimitError

# worker's pytest-asyncio runs in strict mode (unlike api's auto mode —
# see pyproject.toml), so every async test needs this explicitly; no
# other test file in this project has an async test yet to copy the
# convention from.
pytestmark = pytest.mark.asyncio


class _FakeResult:
    def __init__(self, scalar: Any) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeConnection:
    def __init__(self, engine: "_FakeEngine") -> None:
        self._engine = engine

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, stmt: Select | Update) -> _FakeResult:
        if isinstance(stmt, Select):
            return _FakeResult(self._engine.body)
        assert isinstance(stmt, Update)
        # stmt._values maps column name -> BindParameter; .value is the
        # actual bound Python value. Semi-private SQLAlchemy internals
        # (untyped by SQLAlchemy's own stubs), acceptable here since this
        # only ever runs in a test process.
        values = stmt._values or {}  # type: ignore[attr-defined]
        self._engine.updates.append(
            {str(name): bind.value for name, bind in values.items()}  # type: ignore[union-attr]
        )
        return _FakeResult(None)


class _FakeEngine:
    """Stands in for ctx["rag_engine"] — embed_postmortem only ever calls
    .connect() (read) or .begin() (write), both used as async context
    managers, never anything else on the engine itself."""

    def __init__(self, body: str | None) -> None:
        self.body = body
        self.updates: list[dict[str, Any]] = []

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _ctx(engine: _FakeEngine, job_try: int = 1) -> dict:
    return {"rag_engine": engine, "job_try": job_try}


async def test_success_writes_embedding_and_embedded_at_and_clears_error(monkeypatch) -> None:
    async def fake_embed_document(text: str) -> list[float]:
        assert text == "the postmortem body"
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr("app.rag.embed_job.embed_document", fake_embed_document)

    engine = _FakeEngine(body="the postmortem body")
    result = await embed_postmortem(_ctx(engine), str(uuid4()))

    assert result["status"] == "embedded"
    assert engine.updates == [
        {
            "embedding": [0.1, 0.2, 0.3],
            "embedded_at": engine.updates[0]["embedded_at"],
            "embedding_error": None,
        }
    ]
    assert engine.updates[0]["embedded_at"] is not None


async def test_postmortem_not_found_is_skipped_not_an_error(monkeypatch) -> None:
    called = False

    async def fake_embed_document(text: str) -> list[float]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.rag.embed_job.embed_document", fake_embed_document)

    engine = _FakeEngine(body=None)
    result = await embed_postmortem(_ctx(engine), str(uuid4()))

    assert result == {"status": "skipped", "reason": "postmortem_not_found"}
    assert called is False
    assert engine.updates == []


async def test_rate_limit_writes_error_and_raises_retry_with_backoff(monkeypatch) -> None:
    async def fake_embed_document(text: str) -> list[float]:
        raise RateLimitError("rate limited, slow down")

    monkeypatch.setattr("app.rag.embed_job.embed_document", fake_embed_document)

    engine = _FakeEngine(body="body")
    with pytest.raises(Retry) as exc_info:
        await embed_postmortem(_ctx(engine, job_try=1), str(uuid4()))

    assert exc_info.value.defer_score == 20 * 1000  # arq stores defer in ms
    assert len(engine.updates) == 1
    assert "Voyage rate limit" in engine.updates[0]["embedding_error"]
    # A failed attempt must never touch embedding/embedded_at -- a stale
    # prior embedding (if any) survives a failed re-embed rather than
    # being wiped out, see embed_job.py's own module docstring.
    assert set(engine.updates[0]) == {"embedding_error"}


async def test_rate_limit_backoff_increases_with_job_try(monkeypatch) -> None:
    async def fake_embed_document(text: str) -> list[float]:
        raise RateLimitError("rate limited")

    monkeypatch.setattr("app.rag.embed_job.embed_document", fake_embed_document)

    engine = _FakeEngine(body="body")
    with pytest.raises(Retry) as exc_info:
        await embed_postmortem(_ctx(engine, job_try=3), str(uuid4()))

    assert exc_info.value.defer_score == 60 * 1000  # capped at _MAX_DEFER_S


async def test_unexpected_error_writes_error_and_reraises_unchanged(monkeypatch) -> None:
    async def fake_embed_document(text: str) -> list[float]:
        raise ValueError("something else broke")

    monkeypatch.setattr("app.rag.embed_job.embed_document", fake_embed_document)

    engine = _FakeEngine(body="body")
    with pytest.raises(ValueError, match="something else broke"):
        await embed_postmortem(_ctx(engine), str(uuid4()))

    assert engine.updates == [{"embedding_error": "something else broke"}]
