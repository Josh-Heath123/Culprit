# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""The gate's decision: every job the `gate` job needs succeeded.

Phase 41 (docs/DELIVERY_PLAN.md, D1): `gate` is the one check `main`'s
ruleset requires. It runs with `if: always()`, because GitHub counts a
skipped required check as passed, and this decides it from the `needs`
context the workflow hands it as JSON (`NEEDS: ${{ toJSON(needs) }}`):

    {"lint": {"result": "success", "outputs": {}}, ...}

It passes only when every needed job's result is `success`. `failure`,
`cancelled` and `skipped` all fail it: a job skipped because the one before
it failed did not run, and what did not run did not pass. A context naming
no job fails too: a gate that needs nothing has checked nothing.

Standard library only. Exit 0 when every job succeeded, 1 when one did
not, 2 when the context cannot be read. Each job is printed with its
result, so the gate's log says which job held it.

    NEEDS='{"lint": {"result": "success"}}' python3 scripts/ci_gate.py
"""

from __future__ import annotations

import json
import os
import sys

#: The only result that passes the gate.
PASSED = "success"


def decide(needs: object) -> tuple[bool, list[str]]:
    """Whether the gate passes, and one line per job: its name and result.

    Raises ValueError when `needs` is not the shape `toJSON(needs)` gives.
    """
    if not isinstance(needs, dict) or not needs:
        raise ValueError("the needs context names no job")
    lines: list[str] = []
    passed = True
    for name in sorted(needs):
        job = needs[name]
        result = job.get("result") if isinstance(job, dict) else None
        if not isinstance(result, str):
            raise ValueError(f"job {name!r} has no result")
        ok = result == PASSED
        passed = passed and ok
        lines.append(f"{name}: {result}" + ("" if ok else "  <- not success"))
    return passed, lines


def main() -> int:
    raw = os.environ.get("NEEDS")
    if raw is None:
        raw = sys.stdin.read()
    try:
        passed, lines = decide(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as error:
        print(f"gate: cannot read the needs context: {error}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    print("gate: every job succeeded" if passed else "gate: a job did not succeed")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
