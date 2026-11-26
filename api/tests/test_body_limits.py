# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""One cap per kind of route (F44-043, as Q49 ruled), against the real app.

No database: every request here is refused, or passes the cap and is then
refused for something else, before a session is opened. The numbers are
written out, not imported, so a cap that moves fails here.
"""

import json
import pathlib
import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_route_credentials import _routes

BULK = 16 * 1024 * 1024
SMALL = 64 * 1024
SETTING = "CULPRIT_MAX_BULK_BODY_BYTES"
CADDYFILE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "Caddyfile"


def _app() -> FastAPI:
    from app.main import app

    return app


def _refusal(limit: int, route_class: str) -> str:
    sentence = f"the request body is over this route's limit of {limit} bytes ({route_class})"
    if route_class == "bulk":
        sentence += f"; {SETTING} on the control plane raises it"
    return sentence


def _taking_a_body() -> set[str]:
    """Every route the app serves that can take a body: any POST, PUT or
    PATCH, and any route that declares a body parameter."""
    found = set()
    for route in _routes(_app().routes):
        for method in sorted((route.methods or set()) - {"HEAD"}):
            if method in {"POST", "PUT", "PATCH"} or route.dependant.body_params:
                found.add(f"{method} {route.path}")
    assert len(found) >= 30, f"only {sorted(found)}: the walk is missing routes"
    return found


def test_every_route_that_takes_a_body_is_classified() -> None:
    from app.body_limits import ROUTE_CLASSES

    missing = sorted(_taking_a_body() - set(ROUTE_CLASSES))
    assert not missing, f"routes that take a body and are in no class: {missing}"


def test_the_table_names_only_routes_the_api_serves() -> None:
    from app.body_limits import ROUTE_CLASSES

    stale = sorted(set(ROUTE_CLASSES) - _taking_a_body())
    assert not stale, f"classified routes the API does not serve: {stale}"


def test_the_bulk_routes_are_the_ones_the_ruling_names() -> None:
    from app.body_limits import ROUTE_CLASSES

    assert {route for route, kind in ROUTE_CLASSES.items() if kind == "bulk"} == {
        "POST /facts/captures",
        "POST /captures",
        "POST /model/apply",
        "POST /divergences/captures",
        "POST /readings",
        "POST /probes/{probe_id}/run",
        "POST /investigations/{investigation_id}/verifications",
        "POST /investigations",
        "POST /agents/me/tasks/{task_id}/result",
        "POST /agents/me/audit",
    }


def test_the_caps_are_the_ruled_numbers() -> None:
    from app import body_limits

    assert body_limits.DEFAULT_BULK_BODY_BYTES == BULK
    assert body_limits.SMALL_BODY_BYTES == SMALL
    assert body_limits.BULK_SETTING == SETTING


def _api_block(caddyfile: str) -> str:
    start = caddyfile.index("handle_path /api/* {")
    depth = 0
    for index in range(start, len(caddyfile)):
        depth += {"{": 1, "}": -1}.get(caddyfile[index], 0)
        if caddyfile[index] == "}" and depth == 0:
            return caddyfile[start : index + 1]
    raise AssertionError("the /api/* block in the Caddyfile is not closed")


def test_caddy_caps_api_at_the_bulk_cap() -> None:
    """Two readers of one value: Caddy's request_body max_size on /api/*
    is the API's bulk setting, with the API's default."""
    from app import body_limits

    block = _api_block(CADDYFILE.read_text(encoding="utf-8"))
    found = re.search(r"request_body\s*\{\s*max_size\s+\{\$([A-Z_]+):(\d+)\}\s*\}", block)
    assert found, f"no request_body max_size on /api/* in {CADDYFILE}:\n{block}"
    assert found.group(1) == body_limits.BULK_SETTING
    assert int(found.group(2)) == body_limits.DEFAULT_BULK_BODY_BYTES


def test_caddys_own_413_on_api_names_the_limit_and_the_setting() -> None:
    """A body over the bulk cap is refused by Caddy before the API sees it,
    so Caddy's 413 is the one a curl user reads: the one shape, the same
    setting and default."""
    from app import body_limits

    caddyfile = CADDYFILE.read_text(encoding="utf-8")
    found = re.search(r"handle_errors 413 \{.*?respond @api `(.*?)` 413", caddyfile, re.S)
    assert found, "no JSON 413 for /api/* in the Caddyfile"
    expected = _refusal(body_limits.DEFAULT_BULK_BODY_BYTES, "bulk").replace(
        "this route's limit of 16777216",
        f"this API's limit of {{${body_limits.BULK_SETTING}:16777216}}",
    )
    assert json.loads(found.group(1)) == {"detail": expected}


def test_the_api_holds_every_request_to_its_cap() -> None:
    from app.body_limits import BodyLimitMiddleware

    assert any(middleware.cls is BodyLimitMiddleware for middleware in _app().user_middleware)


@pytest.fixture
def client() -> Iterator[TestClient]:
    # No `with`: the lifespan opens database engines, and nothing here
    # reaches one.
    yield TestClient(_app())


def _chunks(body: bytes) -> Iterator[bytes]:
    step = 1 << 20
    for start in range(0, len(body), step):
        yield body[start : start + step]


#: Routes that refuse an unauthenticated request without a database, so
#: a body that passes the cap is answered (401) rather than reaching a
#: session this app never opened. Chunked only where the route reads the
#: body before refusing: a signed route refuses an unsigned request before
#: reading a byte (its chunked case is test_agents_api's, signed), and a
#: DELETE reads none.
CASES = [
    pytest.param("POST", "/auth/change-password", SMALL, "small", "content-length", id="small"),
    pytest.param("POST", "/auth/change-password", SMALL, "small", "chunked", id="small-chunked"),
    pytest.param("POST", "/facts/captures", BULK, "bulk", "content-length", id="bulk"),
    pytest.param("POST", "/facts/captures", BULK, "bulk", "chunked", id="bulk-chunked"),
    pytest.param("POST", "/probes/p-1/run", BULK, "bulk", "content-length", id="bulk-template"),
    pytest.param("DELETE", "/users/u-1", SMALL, "small", "content-length", id="unnamed-small"),
]


@pytest.mark.parametrize(("method", "path", "limit", "route_class", "framing"), CASES)
def test_a_body_at_the_cap_passes_and_one_byte_over_is_refused(
    client: TestClient, method: str, path: str, limit: int, route_class: str, framing: str
) -> None:
    """At the cap, the request passes the cap (and is answered for
    whatever else is wrong with it); one byte over, it is a 413 in the one
    error shape that names the limit, and for a bulk route the setting."""
    for size, refused in ((limit, False), (limit + 1, True)):
        body = b"x" * size
        content = body if framing == "content-length" else _chunks(body)
        response = client.request(method, path, content=content)
        if refused:
            assert response.status_code == 413, (size, response.status_code, response.text[:300])
            assert response.json() == {"detail": _refusal(limit, route_class)}
        else:
            assert response.status_code != 413, (size, response.text[:300])
