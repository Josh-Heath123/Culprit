# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""Phase 44 batch 3, decision 7: the API under strain.

F44-050 (CORS origins trimmed) and F44-044 (one error shape). The
sign-in limit per address (F44-015) and a create's unique violation
(F44-047) are in test_users_api.py, beside the routes they hold.
"""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel


@pytest.mark.parametrize(
    ("raw", "origins"),
    [
        ("https://a.example, https://b.example", ["https://a.example", "https://b.example"]),
        (" https://a.example ,,https://b.example,", ["https://a.example", "https://b.example"]),
        ("http://localhost:5173", ["http://localhost:5173"]),
    ],
)
def test_cors_origins_are_trimmed(raw: str, origins: list[str]) -> None:
    from app.main import cors_origins

    assert cors_origins(raw) == origins


def _shaped(body: Any) -> bool:
    """The one error shape: {"detail": a sentence}, or a 422's list."""
    return (
        isinstance(body, dict)
        and set(body) == {"detail"}
        and isinstance(body["detail"], str | list)
    )


def test_the_api_installs_the_one_error_shape() -> None:
    """app.main answers every error through app/errors.py, the 429 included:
    no handler of its own."""
    from app import errors
    from app.main import app
    from fastapi.exceptions import RequestValidationError
    from slowapi.errors import RateLimitExceeded
    from starlette.exceptions import HTTPException as StarletteHTTPException

    handlers = app.exception_handlers
    assert handlers[RateLimitExceeded] is errors.rate_limited
    assert handlers[RequestValidationError] is errors.redacting_validation_handler
    assert handlers[StarletteHTTPException] is errors.http_error


def test_every_error_answers_in_the_one_shape() -> None:
    from app import errors
    from app.incidents.limiter import limiter

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    errors.install(app)

    class Body(BaseModel):
        name: str

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="no such thing")

    @app.get("/structured")
    async def structured() -> None:
        raise HTTPException(status_code=409, detail={"message": "it moved", "seq": 3})

    @app.post("/validated")
    async def validated(body: Body) -> None:
        return None

    @app.get("/limited")
    @limiter.limit("1/minute")
    async def limited(request: Request) -> dict:
        return {}

    client = TestClient(app)
    answers = {
        "404": client.get("/missing"),
        "409": client.get("/structured"),
        "422": client.post("/validated", json={}),
        "405": client.delete("/missing"),
    }
    client.get("/limited")
    answers["429"] = client.get("/limited")
    for name, response in answers.items():
        assert response.status_code == int(name), (name, response.text)
        assert _shaped(response.json()), (name, response.json())
    assert answers["409"].json()["detail"] == "it moved (seq: 3)"
    assert "1 per 1 minute" in answers["429"].json()["detail"]
