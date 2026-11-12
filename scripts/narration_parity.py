#!/usr/bin/env python3
"""Narration changes nothing but the prose — Phase 35 part 2.

CI runs the e2e job twice, with narration on (the stub provider) and off
(`LLM_PROVIDER=none`). In each, `just agent-e2e` diagnoses the audience
fault through an agent and verifies a wrong fix and the right one. This
script dumps that investigation and its verifications from the control
plane, with what legitimately differs between two runs taken out — ids,
times, durations, capture references, which agent — and compares the two
dumps. Anything else that differs is a narration that changed a record.

    narration_parity.py dump BASE_URL INVESTIGATION_ID OUT.json
        (credentials from CULPRIT_E2E_USERNAME / CULPRIT_E2E_PASSWORD)
    narration_parity.py compare A.json B.json

Standard library only, so it runs on a bare CI runner.
"""

import json
import os
import re
import sys
import urllib.request
from typing import Any

#: Keys whose values differ between two runs of the same loop by nature,
#: wherever they appear: minted ids, record timestamps, which agent.
_VOLATILE_KEY = re.compile(
    r"^(id|investigation_id|agent_id|submitted_by|before_capture|after_capture)$|_at$"
)
#: Inside a reading's `measured`, and only there, a time is volatile too: a
#: duration, a sample array, a token's remaining lifetime. A reading's
#: `expected`, a budget and a verdict are compared (Phase 36 part 2: `_ms`
#: was volatile everywhere, so a declared budget that differed between the
#: legs passed).
_MEASURED_TIME = re.compile(r"_ms$|_us$|_seconds$|^elapsed")
#: Identifiers minted per run, wherever they appear inside text.
_MINTED = re.compile(r"\b(inv|ver|cap|nar|task)-[0-9a-z]{6,}\b")


def _agents(value: Any, found: set[str]) -> set[str]:
    """Every agent the records name (`agent_id`, `submitted_by: agent:<id>`):
    each run pairs its own, and its name also appears inside text."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "agent_id" and isinstance(item, str) and item:
                found.add(item)
            elif key == "submitted_by" and isinstance(item, str) and item.startswith("agent:"):
                found.add(item.removeprefix("agent:"))
            else:
                _agents(item, found)
    elif isinstance(value, list):
        for item in value:
            _agents(item, found)
    return found


def normalised(
    value: Any, agents: frozenset[str] | None = None, *, measured: bool = False
) -> Any:
    if agents is None:
        agents = frozenset(_agents(value, set()))
    if isinstance(value, dict):
        return {
            key: normalised(item, agents, measured=measured or key == "measured")
            for key, item in sorted(value.items())
            if not _VOLATILE_KEY.search(key) and not (measured and _MEASURED_TIME.search(key))
        }
    if isinstance(value, list):
        return [normalised(item, agents, measured=measured) for item in value]
    if isinstance(value, str):
        for agent in sorted(agents, key=len, reverse=True):
            value = value.replace(agent, "<agent>")
        return _MINTED.sub(r"\1-<id>", value)
    return value


def _get(base: str, path: str, token: str | None = None, body: Any = None) -> Any:
    request = urllib.request.Request(
        base.rstrip("/") + "/api" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def dump(base: str, investigation_id: str, out: str) -> int:
    login = _get(
        base,
        "/auth/login",
        body={
            "username": os.environ["CULPRIT_E2E_USERNAME"],
            "password": os.environ["CULPRIT_E2E_PASSWORD"],
        },
    )
    token = login["access_token"]
    investigation = _get(base, f"/investigations/{investigation_id}", token)
    verifications = _get(base, f"/investigations/{investigation_id}/verifications", token)
    raw = {
        "investigation": investigation,
        "verifications": [item["verification"] for item in verifications["items"]],
    }
    # The agent may be named only in a stored row's submitted_by.
    agents = frozenset(_agents(verifications, _agents(raw, set())))
    records = normalised(raw, agents)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"{out}: the investigation and {len(records['verifications'])} verification(s)")
    return 0


def compare(a: str, b: str) -> int:
    with open(a, encoding="utf-8") as left, open(b, encoding="utf-8") as right:
        first, second = json.load(left), json.load(right)
    if first == second:
        print(f"{a} and {b} are identical apart from ids and times")
        return 0
    print(f"{a} and {b} differ beyond ids and times:", file=sys.stderr)
    for line in _diff(first, second, "$"):
        print("  " + line, file=sys.stderr)
    return 1


def _diff(a: Any, b: Any, where: str) -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out += _diff(a.get(key), b.get(key), f"{where}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            out += _diff(x, y, f"{where}[{index}]")
        return out
    return [] if a == b else [f"{where}: {json.dumps(a)[:200]} != {json.dumps(b)[:200]}"]


def main(argv: list[str]) -> int:
    if len(argv) == 5 and argv[1] == "dump":
        return dump(argv[2], argv[3], argv[4])
    if len(argv) == 4 and argv[1] == "compare":
        return compare(argv[2], argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
