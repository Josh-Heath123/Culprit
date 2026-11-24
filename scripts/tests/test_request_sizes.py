# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""scripts/request_sizes.py: the largest bodies, from the api's access lines."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sizes


def _line(**entry: object) -> str:
    return "api-1  | " + json.dumps(entry)


LOG = "\n".join(
    [
        _line(method="POST", path="/investigations", request_bytes=41000, event="http_request"),
        _line(
            method="POST",
            path="/investigations/inv-0123456789abcdef/verifications",
            request_bytes=9000,
            event="http_request",
        ),
        _line(
            method="POST",
            path="/investigations/inv-fedcba9876543210/verifications",
            request_bytes=12000,
            event="http_request",
        ),
        _line(method="GET", path="/investigations", request_bytes=0, event="http_request"),
        _line(event="agent_task_claimed", request_bytes=999999),
        "api-1  | INFO:     Started server process [1]",
    ]
)


def test_the_largest_body_per_route_ids_folded() -> None:
    assert request_sizes.sizes(LOG.splitlines()) == {
        "POST /investigations": 41000,
        "POST /investigations/{id}/verifications": 12000,
        "GET /investigations": 0,
    }


@pytest.mark.parametrize(("cap", "code"), [(None, 0), (164000, 0), (163999, 1)])
def test_the_cap_keeps_four_times_the_largest(
    monkeypatch: pytest.MonkeyPatch, cap: int | None, code: int
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(LOG))
    assert request_sizes.main([] if cap is None else ["--cap", str(cap)]) == code


def test_no_access_line_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("nothing here\n"))
    assert request_sizes.main([]) == 1
