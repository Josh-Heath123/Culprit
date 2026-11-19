# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""scripts/ci_gate.py: the gate passes only when every needed job succeeded.

Phase 41 (D1). Each result a job can have is here: `success` passes, and
`failure`, `skipped` and `cancelled` each fail the gate on their own, among
jobs that all succeeded. `skipped` is the one that matters most: GitHub
counts a skipped required check as passed, and a job skipped because the
one before it failed never ran.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ci_gate

SCRIPT = Path(__file__).resolve().parent.parent / "ci_gate.py"

JOBS = ["lint", "typecheck", "cli", "fault-library", "e2e", "build"]


def needs(**results: str) -> dict:
    """A `toJSON(needs)` context: every job succeeded, but those named."""
    context = {job: {"result": "success", "outputs": {}} for job in JOBS}
    for job, result in results.items():
        context[job.replace("_", "-")] = {"result": result, "outputs": {}}
    return context


def run(context: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "NEEDS": json.dumps(context)},
        capture_output=True,
        text=True,
    )


def test_every_job_succeeded_passes():
    passed, lines = ci_gate.decide(needs())
    assert passed
    assert lines == [f"{job}: success" for job in sorted(JOBS)]
    done = run(needs())
    assert done.returncode == 0, done.stderr
    assert "gate: every job succeeded" in done.stdout


@pytest.mark.parametrize("result", ["failure", "skipped", "cancelled"])
def test_one_job_that_did_not_succeed_fails_the_gate(result):
    passed, lines = ci_gate.decide(needs(fault_library=result))
    assert not passed
    assert f"fault-library: {result}  <- not success" in lines
    done = run(needs(fault_library=result))
    assert done.returncode == 1
    assert f"fault-library: {result}" in done.stdout


def test_a_gate_skipped_by_a_failed_lint_fails():
    # What `if: always()` exists for: lint failed, and everything after it
    # was skipped. Every one of them is named.
    context = needs(lint="failure", typecheck="skipped", cli="skipped", build="skipped")
    passed, lines = ci_gate.decide(context)
    assert not passed
    assert sum("not success" in line for line in lines) == 4


@pytest.mark.parametrize("result", ["", "Success", "neutral", None])
def test_any_other_result_fails(result):
    if result is None:
        with pytest.raises(ValueError):
            ci_gate.decide({"lint": {"outputs": {}}})
        return
    passed, _ = ci_gate.decide(needs(lint=result))
    assert not passed


@pytest.mark.parametrize("context", [{}, [], None, {"lint": "success"}])
def test_a_context_naming_no_job_or_malformed_cannot_pass(context):
    with pytest.raises(ValueError):
        ci_gate.decide(context)
    assert run(context).returncode == 2


def test_unreadable_json_cannot_pass():
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "NEEDS": "{not json"},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
