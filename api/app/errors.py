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
type. That is everything a caller needs to fix the request — an error at
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
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger("api.validation")

#: Dropped from every reported error. `input` is the offending value;
#: `ctx` carries the exception object, which for a pydantic
#: `model_validator` failure stringifies to the message *including the
#: value it complained about*.
_REDACTED_KEYS = ("input", "ctx")


def _scrub(errors: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in dict(error).items() if key not in _REDACTED_KEYS}
        for error in errors
    ]


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
    return JSONResponse({"detail": errors}, status_code=422)


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, redacting_validation_handler)
