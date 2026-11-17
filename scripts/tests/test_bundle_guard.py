"""The self-check job's bundle guard (Phase 38 part 1) is a script inside
.github/workflows/ci-cd.yml. A syntax slip in it is only seen once CI runs,
and it was: a newline inside one of its strings broke the workflow file
itself (run 44087916059, no job started). So the workflow must parse, and
the guard must compile and judge a SARIF file both ways, here.
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci-cd.yml"
STEP = "The bundle budget was judged"


def _guard() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = [s for s in workflow["jobs"]["self-check"]["steps"] if s.get("name") == STEP]
    assert len(steps) == 1, f"the self-check job has {len(steps)} step(s) named {STEP!r}"
    run = steps[0]["run"]
    opening = "python3 - <<'PY'\n"
    assert run.startswith(opening) and run.rstrip().endswith("PY"), run
    return run[len(opening) : run.rstrip().rindex("PY")]


def _judge(tmp_path: Path, notes: list[str]) -> subprocess.CompletedProcess[str]:
    sarif = {
        "runs": [
            {
                "invocations": [
                    {"toolExecutionNotifications": [{"message": {"text": text}} for text in notes]}
                ]
            }
        ]
    }
    (tmp_path / "culprit.sarif").write_text(json.dumps(sarif), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", _guard()], cwd=tmp_path, capture_output=True, text=True, check=False
    )


def test_the_guard_compiles() -> None:
    compile(_guard(), STEP, "exec")


def test_the_guard_passes_a_judged_budget(tmp_path: Path) -> None:
    result = _judge(tmp_path, ["Not checked: culprit-api * nothing to do with builds"])
    assert result.returncode == 0, result.stderr


def test_the_guard_fails_an_unread_build(tmp_path: Path) -> None:
    result = _judge(
        tmp_path,
        ["Not checked: culprit-web build — no build manifest at frontend/dist/.vite/manifest.json"],
    )
    assert result.returncode != 0
    assert "not judged" in result.stderr


def test_the_guard_fails_an_unjudged_entry(tmp_path: Path) -> None:
    result = _judge(
        tmp_path,
        ["Not checked: culprit-web bundle_gzip_bytes_max — budgets[0] budgets the entry"],
    )
    assert result.returncode != 0
