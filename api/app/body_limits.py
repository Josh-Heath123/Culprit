# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""How large a request body each route reads (F44-043, as Q49 ruled).

Every route that takes a body is named here once, in one of two classes:

- **bulk**, bundles and batches: an INTENT bundle (this repository's is
  about 515 KB, and grows with the repository), a capture envelope posted
  with curl, an agent's audit backlog, an investigation or a verification.
  16 MiB unless `CULPRIT_MAX_BULK_BODY_BYTES` says otherwise.
  `frontend/Caddyfile` caps `/api/*` at the same setting and default, and
  `api/tests/test_body_limits.py` reads both files to hold them equal.
- **small**, everything else that takes a body: 64 KiB, the largest body
  measured in CI's e2e and fault-library runs (14,214 bytes, run
  45454853674) times four, rounded up. Not a setting.

A route the table does not name is capped as small, and a route taking a
body that the table does not name fails `test_body_limits.py`: no route is
capped by accident or left uncapped by omission.

`BodyLimitMiddleware` holds every route to its class: a declared
Content-Length over the cap is refused before anything is read, and a
chunked body is counted as it arrives and refused the moment it passes the
cap. The signed-route dependency reads the same table
(`app.agents.dependencies`), so a signature is never checked over a body
the route would refuse. A refusal is a 413 in the one error shape
(app/errors.py) that names the limit and, for a bulk route, the setting.
"""

import json
import os
import re
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, Request

from app.errors import error_body

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

BULK_SETTING = "CULPRIT_MAX_BULK_BODY_BYTES"

#: The bulk cap's default: 16 MiB. frontend/Caddyfile's default is the same
#: number, held to it by test_body_limits.py.
DEFAULT_BULK_BODY_BYTES = 16 * 1024 * 1024

#: The small cap: 14,214 bytes (the largest legitimate body measured in
#: CI, run 45454853674) times four is 56,856; rounded up to 64 KiB.
SMALL_BODY_BYTES = 64 * 1024

RouteClass = Literal["bulk", "small"]

#: Every route that takes a body, by method and path as the API serves it
#: (without Caddy's /api prefix). Q49's ruling names the bulk routes.
ROUTE_CLASSES: dict[str, RouteClass] = {
    # bulk: bundles and batches
    "POST /facts/captures": "bulk",  # an INTENT bundle
    "POST /captures": "bulk",  # a capture envelope
    "POST /model/apply": "bulk",
    "POST /divergences/captures": "bulk",
    "POST /readings": "bulk",
    "POST /probes/{probe_id}/run": "bulk",  # takes no body today (answers 503)
    "POST /investigations/{investigation_id}/verifications": "bulk",
    "POST /investigations": "bulk",
    "POST /agents/me/tasks/{task_id}/result": "bulk",
    "POST /agents/me/audit": "bulk",
    # small: everything else that takes a body
    "POST /auth/login": "small",
    "POST /auth/change-password": "small",
    "POST /model/components": "small",
    "PATCH /model/components/{component_id}": "small",
    "POST /model/components/{component_id}/keys": "small",
    "POST /model/connections": "small",
    "PATCH /model/connections/{connection_id}": "small",
    "POST /model/topology/suggestions/accept": "small",
    "POST /model/topology/suggestions/dismiss": "small",
    "POST /users": "small",
    "PATCH /users/{user_id}": "small",
    "POST /users/{user_id}/reset-password": "small",
    "POST /postmortems": "small",
    "PATCH /postmortems/{postmortem_id}": "small",
    "POST /architecture-decisions": "small",
    "PATCH /architecture-decisions/{decision_id}": "small",
    "POST /ai-change-records": "small",
    "POST /invariant-violations": "small",
    "POST /agents/me/tasks/claim": "small",  # signed; an empty body
    "POST /agents/pairing-codes": "small",
    "POST /agents/register": "small",
    "PATCH /agents/{agent_id}/grants": "small",
    "POST /agents/{agent_id}/revoke": "small",
    "POST /agents/{agent_id}/tasks": "small",
}


def _bulk_body_bytes() -> int:
    raw = os.environ.get(BULK_SETTING, "").strip()
    if not raw:
        return DEFAULT_BULK_BODY_BYTES
    if not raw.isdigit() or int(raw) < SMALL_BODY_BYTES:
        raise RuntimeError(
            f"{BULK_SETTING} must be a whole number of bytes, at least {SMALL_BODY_BYTES}, "
            f"not {raw!r}"
        )
    return int(raw)


#: Read once, at import; a test lowers it with monkeypatch.
BULK_BODY_BYTES = _bulk_body_bytes()


@dataclass(frozen=True)
class Limit:
    route: str  # "METHOD /template", or "" for a route the table does not name
    route_class: RouteClass
    bytes: int

    def refusal(self) -> str:
        """What a 413 says: the limit, and for a bulk route the setting."""
        sentence = (
            f"the request body is over this route's limit of {self.bytes} bytes "
            f"({self.route_class})"
        )
        if self.route_class == "bulk":
            sentence += f"; {BULK_SETTING} on the control plane raises it"
        return sentence


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", template)
    return re.compile(
        "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
    )


#: Literal paths first, so /agents/me/... is never read as /agents/{agent_id}/...
_MATCHERS = sorted(
    ((key, *key.split(" ", 1)) for key in ROUTE_CLASSES),
    key=lambda entry: entry[2].count("{"),
)
_COMPILED = [(key, method, _pattern(path)) for key, method, path in _MATCHERS]


def limit_for(method: str, path: str) -> Limit:
    """The cap on a request to `path` (as served, values in place)."""
    for key, route_method, pattern in _COMPILED:
        if route_method == method and pattern.fullmatch(path):
            route_class = ROUTE_CLASSES[key]
            size = BULK_BODY_BYTES if route_class == "bulk" else SMALL_BODY_BYTES
            return Limit(key, route_class, size)
    return Limit("", "small", SMALL_BODY_BYTES)


def too_large(limit: Limit) -> HTTPException:
    return HTTPException(status_code=413, detail=limit.refusal())


async def capped_body(request: Request) -> bytes:
    """The request's body, refused with a 413 as soon as it is known to be
    over its route's cap: from its Content-Length, or, chunked, as it
    arrives. Kept on the request, so a later request.body() returns it."""
    limit = limit_for(request.method, request.url.path)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit.bytes:
        raise too_large(limit)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit.bytes:
            raise too_large(limit)
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body  # what Request.body() caches
    return body


class BodyLimitMiddleware:
    """Every HTTP request held to its route's cap, before any route reads it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["method"], scope["path"])
        declared = next(
            (value for name, value in scope.get("headers", ()) if name == b"content-length"),
            b"",
        )
        if declared.isdigit() and int(declared) > limit.bytes:
            await _refuse(send, limit)
            return

        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit.bytes:
                    # Raised inside the route, so the app's own handler
                    # answers it in the one shape (app/errors.py).
                    raise too_large(limit)
            return message

        await self.app(scope, counted, send)


async def _refuse(send: Send, limit: Limit) -> None:
    body = json.dumps(error_body(limit.refusal())).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
