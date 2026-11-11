"""scripts/narration_parity.py: what it ignores, and what it must not.

The parity gate compares the agent loop's records with narration on and
off. It is a gate only if a difference that matters turns it red — shown
here by changing a verdict and a reading — while ids, times and capture
references, which differ between any two runs, do not.
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import narration_parity

RECORDS = {
    "investigation": {
        "id": "inv-0123456789abcdef",
        "opened_at": "2026-11-11T10:00:00Z",
        "readings": [
            {
                "id": "r1",
                "reading": {
                    "probe_id": "probe.auth.token_shape",
                    "verdict": "fail",
                    "taken_at": "2026-11-11T10:00:01Z",
                    "agent_id": "e2e-agent-1",
                    "measured": {"elapsed_ms": 12, "aud": "orders"},
                },
            }
        ],
    },
    "verifications": [
        {
            "id": "ver-0123456789abcdef",
            "investigation_id": "inv-0123456789abcdef",
            "verdict": "verified",
            "before_capture": "cap-1",
            "reason": "verified against inv-0123456789abcdef",
        }
    ],
}


def _write(tmp_path: Path, name: str, records: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(narration_parity.normalised(records)), encoding="utf-8")
    return str(path)


def test_ids_times_and_durations_are_not_differences(tmp_path: Path) -> None:
    other = copy.deepcopy(RECORDS)
    other["investigation"]["id"] = "inv-fedcba9876543210"
    other["investigation"]["opened_at"] = "2026-11-12T00:00:00Z"
    reading = other["investigation"]["readings"][0]["reading"]
    reading.update(taken_at="2026-11-12T00:00:01Z", agent_id="e2e-agent-2")
    reading["measured"]["elapsed_ms"] = 99
    other["verifications"][0].update(
        id="ver-fedcba9876543210",
        before_capture="cap-2",
        reason="verified against inv-fedcba9876543210",
    )
    a, b = _write(tmp_path, "a.json", RECORDS), _write(tmp_path, "b.json", other)
    assert narration_parity.compare(a, b) == 0


def test_the_runs_agent_named_in_text_and_a_tokens_lifetime_are_not_differences(
    tmp_path: Path,
) -> None:
    """Found in CI: each run pairs its own agent, whose name appears inside
    a reason as well as under agent_id; a token's remaining lifetime is a
    time."""
    first = copy.deepcopy(RECORDS)
    first["investigation"]["note"] = "a verify task, sent to agent e2e-agent-1, measures it"
    first["investigation"]["readings"][0]["reading"]["measured"]["expires_in_seconds"] = 3597
    second = copy.deepcopy(first)
    second["investigation"]["readings"][0]["reading"]["agent_id"] = "e2e-agent-2"
    second["investigation"]["note"] = "a verify task, sent to agent e2e-agent-2, measures it"
    second["investigation"]["readings"][0]["reading"]["measured"]["expires_in_seconds"] = 3598
    a, b = _write(tmp_path, "a.json", first), _write(tmp_path, "b.json", second)
    assert narration_parity.compare(a, b) == 0


def test_a_verdict_or_a_reading_that_differs_is_a_difference(tmp_path: Path) -> None:
    for change in (
        lambda r: r["verifications"][0].update(verdict="not_resolved"),
        lambda r: r["investigation"]["readings"][0]["reading"]["measured"].update(aud="payments"),
        lambda r: r["investigation"]["readings"][0]["reading"].update(verdict="pass"),
    ):
        other = copy.deepcopy(RECORDS)
        change(other)
        a, b = _write(tmp_path, "a.json", RECORDS), _write(tmp_path, "b.json", other)
        assert narration_parity.compare(a, b) == 1
