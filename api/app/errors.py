# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""A 422 that does not echo the request body back.

FastAPI's default `RequestValidationError` handler includes an `input`
field on every error, containing the offending value — and, for a nested
model, the whole enclosing object. That is a good debugging aid and a bad
default here.

Found while testing the Phase 28 plane check: a capture bundle carrying
`postgresql://u:hunter2@db/orders` was correctly refused, and the refusal
put the DSN in the response body, from where it goes into this API's own
structured access log and into the CI log of whatever posted it. The
caller already had the value, so nothing is disclosed to a third party —
but a credential written into two log stores is exactly the outcome
`configured_facts`, `ValueShape` and the manifest's credential refusal all
exist to prevent, and it would be strange to hold extractors to that rule
while the error path quietly breaks it.

**What is kept:** the location (`loc`), the message (`msg`) and the error
type. Since Phase 44 batch 1 (F44-022) the message names the field and
never the value: a validator that quoted what it refused (a subject, the
words of a change, a grant name) has that value replaced in `msg` before
it leaves, and what remains passes the shared credential pattern. That
is everything a caller needs to fix the request — an error at
`facts.0` saying a fact is on the CONFIGURED plane while the capture
declares INTENT names both the field and the problem. Only the echoed
value goes.

Applied to the whole app rather than one router. No endpoint benefits
from having its request body reflected back, and scoping it to the one
that currently posts secrets would leave the next one to rediscover this.
"""

from collections.abc import Sequence
from typing import Any

import structlog
from culprit_model.redaction import redact_credentials
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger("api.validation")

#: Dropped from every reported error. `input` is the offending value;
#: `ctx` carries the exception object, which for a pydantic
#: `model_validator` failure stringifies to the message *including the
#: value it complained about*.
_REDACTED_KEYS = ("input", "ctx")


#: What a refused value is called in a message, in its place.
_THE_VALUE = "(the value given)"


def _strings(value: Any) -> list[str]:
    """Every string in a refused input, a nested body's included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list | tuple):
        return [text for item in value for text in _strings(item)]
    return []


def _message(error: dict[str, Any]) -> str:
    """The error's message with every value it was given taken out: each
    string in the input, quoted or not, longest first, then the shared
    credential pattern over what is left."""
    message = str(error.get("msg", ""))
    for text in sorted(set(_strings(error.get("input"))), key=len, reverse=True):
        if text.strip():
            message = message.replace(repr(text), _THE_VALUE).replace(text, _THE_VALUE)
    return redact_credentials(message)


def _scrub(errors: Sequence[Any]) -> list[dict[str, Any]]:
    scrubbed = []
    for error in errors:
        kept = {key: value for key, value in dict(error).items() if key not in _REDACTED_KEYS}
        if "msg" in kept:
            kept["msg"] = _message(dict(error))
        scrubbed.append(kept)
    return scrubbed


async def redacting_validation_handler(
    request: Request, exc: Exception
) -> Response:
    """Returns FastAPI's own 422 shape with the echoed values removed."""
    errors = _scrub(exc.errors()) if isinstance(exc, RequestValidationError) else []
    # Logged as a count and the field paths, never the values — the same
    # rule the response now follows.
    logger.warning(
        "request_validation_failed",
        path=request.url.path,
        method=request.method,
        error_count=len(errors),
        fields=[".".join(str(part) for part in error.get("loc", ())) for error in errors],
    )
    return JSONResponse(error_body(errors), status_code=422)


# ---- one error shape (F44-044, Phase 44 batch 3) -------------------------------------
#
# Every error this API answers is {"detail": a sentence}, or, for a 422,
# {"detail": [the scrubbed validation errors]} - the shape FastAPI's own
# HTTPException already gave most routes. The dashboard reads that and
# nothing else (frontend/src/lib/errors.ts). Two routes answered otherwise:
# the rate limit ({"error": ...}) and the audit chain's 409 ({"detail":
# {message, seq, hash}}). Both now pass through here, and a detail that is
# not a sentence is made one rather than sent as it came.


def error_body(detail: str | list[Any]) -> dict[str, Any]:
    """The one error body."""
    return {"detail": detail}


def _sentence(detail: Any) -> str | list[Any]:
    if isinstance(detail, str | list):
        return detail
    if isinstance(detail, dict):
        message = str(detail.get("message", ""))
        rest = ", ".join(f"{key}: {value}" for key, value in detail.items() if key != "message")
        return f"{message} ({rest})" if message and rest else message or rest
    return str(detail)


async def http_error(request: Request, exc: Exception) -> Response:
    """Every HTTPException, in the one shape, its headers kept."""
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    return JSONResponse(
        error_body(_sentence(exc.detail)), status_code=exc.status_code, headers=exc.headers
    )


async def rate_limited(request: Request, exc: Exception) -> Response:
    """A 429, in the one shape, logged (Phase 10: no silent 429s), with
    slowapi's Retry-After and X-RateLimit headers."""
    detail = str(getattr(exc, "detail", ""))
    logger.warning(
        "rate_limit_exceeded", path=request.url.path, method=request.method, detail=detail
    )
    response = JSONResponse(error_body(f"Rate limit exceeded: {detail}"), status_code=429)
    limiter = getattr(request.app.state, "limiter", None)
    view_limit = getattr(request.state, "view_rate_limit", None)
    if limiter is not None and view_limit is not None:
        response = limiter._inject_headers(response, view_limit)
    return response


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, redacting_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RateLimitExceeded, rate_limited)
