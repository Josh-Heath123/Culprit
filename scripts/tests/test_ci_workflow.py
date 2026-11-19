"""The CI workflow's shape that makes `gate` mean something (Phase 41).

`gate` is the one check `main`'s ruleset requires (docs/DELIVERY_PLAN.md,
D1), so what it needs is what a merge is held to. This parses
.github/workflows/ci-cd.yml and holds:

- `gate` needs every job but itself and `deploy`, so a job added later and
  left out of it fails here. `deploy` is left out by name, for its reason:
  it runs only on a hand-started run of main, after `build` and `e2e`, and
  is skipped on every pull request.
- `gate` runs `if: always()` and decides with scripts/ci_gate.py from
  `toJSON(needs)`: GitHub counts a skipped required check as passed.
- Every job has `timeout-minutes`, at least 10. A job that calls a reusable
  workflow cannot set one, so every job of the workflow it calls must.
- `concurrency:` cancels a superseded run on a pull request only: every
  other event is its own group, so a push to main is never cancelled, nor
  left pending behind another.
- The fault library needs `lint` alone (decision 4).
- Nothing lets a job's failure through, or skips one by the files a change
  touches (D5): no `continue-on-error`, no path filter.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci-cd.yml"

#: Jobs `gate` does not need, and why.
NOT_GATED = {
    "gate": "the gate itself",
    "deploy": "runs only on a hand-started run of main, after build and e2e",
}

GROUP = (
    "${{ github.event_name == 'pull_request' && "
    "format('ci-pr-{0}', github.event.pull_request.number) || "
    "format('ci-run-{0}', github.run_id) }}"
)
CANCEL = "${{ github.event_name == 'pull_request' }}"

#: The least timeout-minutes a job may have (decision 6).
FLOOR_MINUTES = 10


def load(path: Path) -> dict:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict) and isinstance(workflow.get("jobs"), dict), path
    return workflow


def needs_of(job: dict) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def check_gate(workflow: dict) -> list[str]:
    """Why the gate does not hold every job, or [] when it does."""
    jobs = workflow["jobs"]
    problems = []
    gate = jobs.get("gate")
    if gate is None:
        return ["the workflow has no gate job"]
    for name in NOT_GATED:
        if name not in jobs:
            problems.append(f"{name} is listed as not gated but is not a job")
    want = set(jobs) - set(NOT_GATED)
    got = set(needs_of(gate))
    for name in sorted(want - got):
        problems.append(f"gate does not need {name}")
    for name in sorted(got - want):
        problems.append(f"gate needs {name}, which is not a job it may need")
    if gate.get("if") != "always()":
        problems.append(f"gate runs if {gate.get('if')!r}, not always()")
    steps = gate.get("steps", [])
    if not any(
        step.get("run") == "python3 scripts/ci_gate.py"
        and step.get("env", {}).get("NEEDS") == "${{ toJSON(needs) }}"
        for step in steps
    ):
        problems.append("gate does not run scripts/ci_gate.py on toJSON(needs)")
    deploy = jobs.get("deploy", {})
    if "github.event_name == 'workflow_dispatch'" not in str(deploy.get("if", "")):
        problems.append("deploy is not gated, but no longer runs only on a hand-started run")
    return problems


def check_timeouts(workflow: dict) -> list[str]:
    problems = []
    for name, job in workflow["jobs"].items():
        if "uses" in job:
            called = load(ROOT / job["uses"].removeprefix("./"))
            for inner, each in called["jobs"].items():
                problems += check_timeout(f"{name} / {inner}", each)
        else:
            problems += check_timeout(name, job)
    return problems


def check_timeout(name: str, job: dict) -> list[str]:
    minutes = job.get("timeout-minutes")
    if not isinstance(minutes, int):
        return [f"{name} has no timeout-minutes"]
    if minutes < FLOOR_MINUTES:
        return [f"{name} times out at {minutes} minutes, under {FLOOR_MINUTES}"]
    return []


def check_concurrency(workflow: dict) -> list[str]:
    problems = []
    concurrency = workflow.get("concurrency")
    if not isinstance(concurrency, dict):
        return ["the workflow has no concurrency block"]
    group, cancel = concurrency.get("group"), concurrency.get("cancel-in-progress")
    if group != GROUP:
        problems.append(
            f"concurrency group is {group!r}, want one per pull request and one per run otherwise"
        )
    if cancel != CANCEL:
        problems.append(f"cancel-in-progress is {cancel!r}, want pull requests only")
    for name, job in workflow["jobs"].items():
        if "concurrency" in job:
            problems.append(f"{name} sets its own concurrency")
    return problems


def check_no_way_around(path: Path) -> list[str]:
    problems = []
    workflow = load(path)
    triggers = workflow.get(True, workflow.get("on", {}))  # YAML 1.1 reads `on` as true
    for event, spec in (triggers or {}).items():
        if isinstance(spec, dict) and ({"paths", "paths-ignore"} & set(spec)):
            problems.append(f"{path.name}: {event} has a path filter")
    for name, job in workflow["jobs"].items():
        if "continue-on-error" in job:
            problems.append(f"{path.name}: {name} continues on error")
        for step in job.get("steps", []):
            if "continue-on-error" in step:
                problems.append(f"{path.name}: a step of {name} continues on error")
    return problems


@pytest.fixture(scope="module")
def workflow() -> dict:
    return load(WORKFLOW)


def test_the_gate_needs_every_job_but_deploy(workflow):
    assert check_gate(workflow) == []


def test_every_job_has_a_timeout(workflow):
    assert check_timeouts(workflow) == []


def test_only_a_pull_request_run_is_cancelled(workflow):
    assert check_concurrency(workflow) == []


def test_the_fault_library_needs_lint_alone(workflow):
    assert needs_of(workflow["jobs"]["fault-library"]) == ["lint"]


@pytest.mark.parametrize("path", [WORKFLOW, WORKFLOWS / "images.yml"], ids=lambda p: p.name)
def test_no_path_filter_and_no_failure_let_through(path):
    assert check_no_way_around(path) == []


# Each check, red on the mutation it exists for.


def test_a_job_left_out_of_the_gate_is_named(workflow):
    jobs = dict(workflow["jobs"])
    jobs["new-check"] = {"runs-on": "ubuntu-latest", "timeout-minutes": 10, "steps": []}
    assert check_gate({**workflow, "jobs": jobs}) == ["gate does not need new-check"]


def test_a_gate_needing_deploy_or_less_is_named(workflow):
    gate = dict(workflow["jobs"]["gate"])
    gate["needs"] = [n for n in needs_of(gate) if n != "e2e"] + ["deploy"]
    problems = check_gate({**workflow, "jobs": {**workflow["jobs"], "gate": gate}})
    assert problems == [
        "gate does not need e2e",
        "gate needs deploy, which is not a job it may need",
    ]


@pytest.mark.parametrize("condition", [None, "success()", "!cancelled()"])
def test_a_gate_that_can_be_skipped_is_named(workflow, condition):
    gate = {k: v for k, v in workflow["jobs"]["gate"].items() if k != "if"}
    if condition:
        gate["if"] = condition
    problems = check_gate({**workflow, "jobs": {**workflow["jobs"], "gate": gate}})
    assert problems == [f"gate runs if {condition!r}, not always()"]


def test_a_job_without_a_timeout_is_named(workflow):
    lint = {k: v for k, v in workflow["jobs"]["lint"].items() if k != "timeout-minutes"}
    short = {**workflow["jobs"]["kind-capture"], "timeout-minutes": 5}
    jobs = {**workflow["jobs"], "lint": lint, "kind-capture": short}
    assert check_timeouts({**workflow, "jobs": jobs}) == [
        "lint has no timeout-minutes",
        "kind-capture times out at 5 minutes, under 10",
    ]


def test_a_called_workflows_job_without_a_timeout_is_named(tmp_path, monkeypatch):
    called = tmp_path / ".github" / "workflows" / "called.yml"
    called.parent.mkdir(parents=True)
    called.write_text("jobs:\n  inner:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    caller = {"jobs": {"outer": {"uses": "./.github/workflows/called.yml"}}}
    assert check_timeouts(caller) == ["outer / inner has no timeout-minutes"]


@pytest.mark.parametrize(
    "concurrency",
    [
        {"group": GROUP, "cancel-in-progress": True},
        {"group": "${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": CANCEL},
        None,
    ],
)
def test_cancelling_a_push_to_main_is_named(workflow, concurrency):
    mutated = {k: v for k, v in workflow.items() if k != "concurrency"}
    if concurrency is not None:
        mutated["concurrency"] = concurrency
    assert check_concurrency(mutated) != []


def test_a_way_around_is_named(tmp_path):
    path = tmp_path / "w.yml"
    path.write_text(
        "on:\n  pull_request:\n    paths-ignore: ['docs/**']\n"
        "jobs:\n  a:\n    continue-on-error: true\n    steps:\n"
        "      - run: x\n        continue-on-error: true\n",
        encoding="utf-8",
    )
    assert check_no_way_around(path) == [
        "w.yml: pull_request has a path filter",
        "w.yml: a continues on error",
        "w.yml: a step of a continues on error",
    ]
