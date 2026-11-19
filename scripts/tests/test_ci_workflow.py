# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

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
- Every `go test` a job runs, in a step or in a `just` recipe a step calls,
  times out in at most half the job's `timeout-minutes` (Phase 42, C3), so
  Go's own timeout fires first and prints the stack that names a hung test.
  A `go test` without `-timeout` has Go's default, 10 minutes.
"""

import math
import re
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

JUSTFILE = ROOT / "justfile"

#: `go test`'s own timeout when none is given.
GO_DEFAULT_TIMEOUT_MINUTES = 10.0

#: A `go test` command, to the end of its line or an unquoted &, ; or |
#: (a -run pattern's | is inside quotes).
GO_TEST = re.compile(r"""\bgo test\b(?:[^\n&;|'"]|'[^'\n]*'|"[^"\n]*")*""")
#: `-timeout` (or `-test.timeout`) and its value, as Go reads it.
GO_TIMEOUT = re.compile(r"-(?:test\.)?timeout[= ](\S+)")
#: One part of a Go duration ("1h30m" is two).
GO_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|us|µs|ns|m|s)")
GO_DURATION_MINUTES = {"h": 60, "m": 1, "s": 1 / 60, "ms": 1 / 60_000,
                       "us": 1 / 60_000_000, "µs": 1 / 60_000_000, "ns": 1 / 60_000_000_000}
JUST_CALL = re.compile(r"\bjust ([a-z_][a-z0-9_-]*)")
RECIPE = re.compile(r"^@?([a-z_][a-z0-9_-]*)(?: [^:\n]*)?:(?!=)(.*)$")


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


def recipes(justfile: str) -> dict[str, tuple[list[str], str]]:
    """Each recipe in a justfile: the recipes it depends on, and its body."""
    found: dict[str, tuple[list[str], str]] = {}
    name, deps, body = None, [], []
    # A line at column 0 that is not a recipe ends the one before it; the
    # sentinel ends the last.
    for line in [*justfile.splitlines(), "# end"]:
        header = RECIPE.match(line)
        if header and not line.startswith((" ", "\t")):
            if name:
                found[name] = (deps, "\n".join(body))
            name, body = header.group(1), []
            deps = [d.strip("@") for d in header.group(2).split("#")[0].split()]
            deps = [d for d in deps if re.fullmatch(r"[a-z_][a-z0-9_-]*", d)]
        elif name and (line.startswith((" ", "\t")) or not line.strip()):
            body.append(line)
        elif name:
            found[name] = (deps, "\n".join(body))
            name, deps, body = None, [], []
    return found


def go_tests(text: str, justfile: dict, seen: frozenset = frozenset()) -> list[str]:
    """Every `go test` command in `text`, and in the recipes it calls."""
    commands = [m.group(0).strip() for m in GO_TEST.finditer(text)]
    for recipe in JUST_CALL.findall(text):
        commands += recipe_go_tests(recipe, justfile, seen)
    return commands


def recipe_go_tests(recipe: str, justfile: dict, seen: frozenset) -> list[str]:
    """Every `go test` a recipe runs: its dependencies first, then its body."""
    if recipe in seen or recipe not in justfile:
        return []
    deps, body = justfile[recipe]
    commands: list[str] = []
    for dep in deps:
        commands += recipe_go_tests(dep, justfile, seen | {recipe})
    return commands + go_tests(body, justfile, seen | {recipe})


def go_timeout_minutes(command: str) -> float:
    """The minutes after which Go stops `command`: its `-timeout`, read as a
    whole Go duration ("1h30m", "30m0s"), or Go's default. `-timeout 0`
    turns Go's timeout off, so it, and a value that is not a duration, are
    read as never: over any job's half."""
    match = GO_TIMEOUT.search(command)
    if not match:
        return GO_DEFAULT_TIMEOUT_MINUTES
    value = match.group(1).strip("'\"")
    parts = GO_DURATION_PART.findall(value)
    if not parts or "".join(n + u for n, u in parts) != value:
        return math.inf
    minutes = sum(float(n) * GO_DURATION_MINUTES[u] for n, u in parts)
    return minutes if minutes > 0 else math.inf


def check_go_timeouts(workflow: dict, justfile: dict) -> list[str]:
    """Why a job's `go test` could outlast half the job, or []."""
    problems = []
    for name, job in workflow["jobs"].items():
        minutes = job.get("timeout-minutes")
        if not isinstance(minutes, int):
            continue  # check_timeouts names it
        text = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
        for command in go_tests(text, justfile):
            inner = go_timeout_minutes(command)
            if inner > minutes / 2:
                problems.append(
                    f"{name}: `{command[:60]}` times out at {inner:g} minutes, "
                    f"over half the job's {minutes}"
                )
    return problems


@pytest.fixture(scope="module")
def justfile() -> dict:
    return recipes(JUSTFILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow() -> dict:
    return load(WORKFLOW)


def test_the_gate_needs_every_job_but_deploy(workflow):
    assert check_gate(workflow) == []


def test_every_job_has_a_timeout(workflow):
    assert check_timeouts(workflow) == []


def test_only_a_pull_request_run_is_cancelled(workflow):
    assert check_concurrency(workflow) == []


def test_every_go_test_times_out_before_its_job(workflow, justfile):
    assert check_go_timeouts(workflow, justfile) == []
    # The rule reads what it must: the jobs that run Go, and the recipe e2e
    # calls for the agent's test.
    seen = {
        name
        for name, job in workflow["jobs"].items()
        if go_tests("\n".join(str(s.get("run", "")) for s in job.get("steps", [])), justfile)
    }
    assert {"cli", "kind-capture", "fault-library", "e2e"} <= seen, seen


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


def test_a_go_test_outlasting_half_its_job_is_named(workflow, justfile):
    job = dict(workflow["jobs"]["fault-library"])
    job["steps"] = [{"run": "cd cli && go test ./cmd/culprit -run X -timeout 30m"}]
    assert check_go_timeouts({"jobs": {"fault-library": job}}, justfile) == [
        "fault-library: `go test ./cmd/culprit -run X -timeout 30m` times out at 30 "
        "minutes, over half the job's 35"
    ]


def test_a_go_test_with_no_timeout_has_gos_default(workflow, justfile):
    job = {**workflow["jobs"]["kind-capture"], "steps": [{"run": "cd cli && go test ./..."}]}
    assert check_go_timeouts({"jobs": {"kind-capture": job}}, justfile) == [
        "kind-capture: `go test ./...` times out at 10 minutes, over half the job's 10"
    ]


def test_a_recipe_a_step_calls_is_read():
    justfile = recipes(
        "agent-e2e: build\n    cd cli && go test ./cmd/culprit -timeout 30m\n\n"
        "build:\n    go test ./x -timeout 1h\n"
    )
    job = {"timeout-minutes": 30, "steps": [{"run": "just agent-e2e"}]}
    assert check_go_timeouts({"jobs": {"e2e": job}}, justfile) == [
        "e2e: `go test ./x -timeout 1h` times out at 60 minutes, over half the job's 30",
        "e2e: `go test ./cmd/culprit -timeout 30m` times out at 30 minutes, over half the job's 30",
    ]


#: The tools `just lint` and CI's lint job run by uvx, pinned (Phase 42).
PINNED_TOOLS = ["reuse[charset-normalizer]==", "cffconvert@"]


def tool_pins(text: str) -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for tool in PINNED_TOOLS:
        at = 0
        while (at := text.find(tool, at)) >= 0:
            start = at + len(tool)
            end = start
            while end < len(text) and (text[end].isalnum() or text[end] == "."):
                end += 1
            pins.setdefault(tool, []).append(text[start:end])
            at = end
    return pins


def test_the_lint_tools_are_pinned_alike_locally_and_in_ci(workflow, justfile):
    lint_job = "\n".join(str(s.get("run", "")) for s in workflow["jobs"]["lint"]["steps"])
    lint_recipe = justfile["lint"][1]
    ci, local = tool_pins(lint_job), tool_pins(lint_recipe)
    for tool in PINNED_TOOLS:
        assert ci.get(tool), f"CI's lint job does not run {tool}"
        assert local.get(tool), f"`just lint` does not run {tool}"
        versions = set(ci[tool]) | set(local[tool])
        assert len(versions) == 1, f"{tool} is pinned to {sorted(versions)}"
        assert all(part.isdigit() for part in versions.pop().split(".")), tool


@pytest.mark.parametrize(
    ("flag", "minutes"),
    [
        ("-timeout 17m", 17),
        ("-timeout=17m", 17),
        ("-timeout 30m0s", 30),
        ("-timeout 1h30m", 90),
        ("-timeout 1m30s", 1.5),
        ("-timeout 90s", 1.5),
        ("-test.timeout 20m", 20),
        ("", 10),
        ("-timeout 0", math.inf),
        ("-timeout 0s", math.inf),
        ("-timeout forever", math.inf),
    ],
)
def test_a_go_timeout_is_read_as_go_reads_it(flag, minutes):
    assert go_timeout_minutes(f"go test ./cmd/culprit -run X {flag}".strip()) == minutes


@pytest.mark.parametrize("flag", ["-timeout 0", "-timeout 30m0s", "-timeout 1h30m"])
def test_a_timeout_go_reads_as_longer_is_named(workflow, justfile, flag):
    job = dict(workflow["jobs"]["fault-library"])
    job["steps"] = [{"run": f"cd cli && go test ./cmd/culprit -run X {flag}"}]
    problems = check_go_timeouts({"jobs": {"fault-library": job}}, justfile)
    assert len(problems) == 1 and "over half the job's 35" in problems[0], problems


# Phase 43 (D7, decision 3): every external action pinned to a commit.

#: A `uses:` line, as written (YAML drops the comment that names the version).
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s+(\S+)(.*)$", re.M)
#: An action pinned to a full commit: owner/repo[/path]@<40 hex>.
PINNED_ACTION = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}")
#: The version the pin was resolved from, as a comment: `# v4.4.0`.
VERSION_COMMENT = re.compile(r"\s+# v\d+\.\d+\.\d+")

DEPENDABOT = ROOT / ".github" / "dependabot.yml"

#: A full commit SHA, for the cases below.
CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"


def check_pins(text: str, name: str) -> list[str]:
    """Why an action in a workflow's text is not pinned to a commit, or []."""
    problems = []
    for target, rest in USES_LINE.findall(text):
        if target.startswith("./"):
            continue  # a reusable workflow in this repository, not an action
        if not PINNED_ACTION.fullmatch(target):
            problems.append(f"{name}: `{target}` is not pinned to a full commit SHA")
        elif not VERSION_COMMENT.fullmatch(rest.rstrip()):
            problems.append(f"{name}: `{target}` names no version in a `# vX.Y.Z` comment")
    return problems


def workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def workflow_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in workflow_files()}


def parsed_uses(workflow: dict) -> list[str]:
    """Every `uses:` value GitHub would run, from the parsed workflow: a
    job's (a reusable workflow) and each step's, in whatever YAML style."""
    found = []
    for job in workflow.get("jobs", {}).values():
        if "uses" in job:
            found.append(str(job["uses"]))
        found += [str(step["uses"]) for step in job.get("steps", []) if "uses" in step]
    return found


def test_every_action_is_pinned_to_a_commit():
    texts = workflow_texts()
    assert set(texts) >= {"ci-cd.yml", "images.yml", "cli-release.yml"}, sorted(texts)
    read = sum(len(USES_LINE.findall(t)) for t in texts.values())
    assert read > 40, f"the check reads {read} uses: lines: too few"
    problems = [p for name, text in texts.items() for p in check_pins(text, name)]
    for name, text in texts.items():
        problems += check_parsed_pins(yaml.safe_load(text), text, name)
    assert problems == []


def check_parsed_pins(workflow: dict, text: str, name: str) -> list[str]:
    """What the line reading misses: a `uses:` in flow style
    (`- {uses: x@v4}`) runs all the same."""
    problems = []
    values = parsed_uses(workflow)
    for target in values:
        if not target.startswith("./") and not PINNED_ACTION.fullmatch(target):
            problems.append(f"{name}: `{target}` is not pinned to a full commit SHA")
    lines = len(USES_LINE.findall(text))
    if lines != len(values):
        problems.append(f"{name}: {len(values)} uses: values but {lines} uses: lines (flow style?)")
    return problems


def test_a_flow_style_uses_is_named():
    text = "jobs:\n  a:\n    steps:\n      - { uses: actions/checkout@v4 }\n"
    assert check_parsed_pins(yaml.safe_load(text), text, "w.yml") == [
        "w.yml: `actions/checkout@v4` is not pinned to a full commit SHA",
        "w.yml: 1 uses: values but 0 uses: lines (flow style?)",
    ]


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("      - uses: actions/checkout@v4", "not pinned to a full commit SHA"),
        ("        uses: pypa/gh-action-pypi-publish@release/v1", "not pinned to a full commit SHA"),
        ("      - uses: actions/checkout@11d5960", "not pinned to a full commit SHA"),
        ("      - uses: docker://alpine:3.20", "not pinned to a full commit SHA"),
        (f"      - uses: actions/checkout@{CHECKOUT_SHA}", "names no version"),
        (f"      - uses: actions/checkout@{CHECKOUT_SHA} # v4", "names no version"),
    ],
)
def test_an_unpinned_action_is_named(line, problem):
    problems = check_pins(f"jobs:\n  a:\n    steps:\n{line}\n", "w.yml")
    assert len(problems) == 1 and problem in problems[0], problems


def test_a_pinned_action_and_a_local_workflow_pass():
    text = (
        f"      - uses: actions/checkout@{CHECKOUT_SHA} # v4.4.0\n"
        "    uses: ./.github/workflows/images.yml\n"
        f"      - uses: github/codeql-action/upload-sarif@{CHECKOUT_SHA} # v4.39.3\n"
    )
    assert check_pins(text, "w.yml") == []


def test_dependabot_keeps_the_action_pins_current():
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert config["version"] == 2
    (update,) = config["updates"]  # one ecosystem: no other version updates
    assert update["package-ecosystem"] == "github-actions"
    assert update["directory"] == "/"
    assert update["schedule"]["interval"] == "weekly"
    (group,) = update["groups"].values()  # every update in one pull request
    assert group["patterns"] == ["*"]


# Phase 43 (D7, decision 6): every job's permissions, declared.

READ = {"contents": "read"}
ATTEST = {"id-token": "write", "attestations": "write"}

#: What each workflow grants by default, and what each job ends up with:
#: its own `permissions:` where it sets them, the workflow's otherwise. Only
#: the two jobs that attest hold the attestation permissions.
PERMISSIONS = {
    "ci-cd.yml": {
        "workflow": READ,
        "jobs": {
            "lint": READ,
            "typecheck": READ,
            "cli": READ,
            "self-check": {**READ, "security-events": "write"},
            "kind-capture": READ,
            "fault-library": READ,
            "test": READ,
            "migration-round-trip": READ,
            "e2e": READ,
            "narration-parity": READ,
            # It calls images.yml, whose jobs cannot hold more than this.
            "build": {**READ, "packages": "write", **ATTEST},
            "deploy": READ,
            "gate": READ,
        },
    },
    "images.yml": {
        "workflow": READ,
        "jobs": {
            "build": READ,
            "publish": {**READ, "packages": "write", **ATTEST},
        },
    },
    "cli-release.yml": {
        "workflow": {"contents": "write"},
        "jobs": {
            "release": {"contents": "write", **ATTEST},
            "publish-pypi": {"id-token": "write"},
            "publish-npm": {"id-token": "write"},
        },
    },
}


def check_permissions(name: str, workflow: dict, declared: dict) -> list[str]:
    problems = []
    if workflow.get("permissions") != declared["workflow"]:
        granted = workflow.get("permissions")
        problems.append(f"{name}: the workflow grants {granted}, declared {declared['workflow']}")
    jobs = workflow["jobs"]
    for job in sorted(set(jobs) - set(declared["jobs"])):
        problems.append(f"{name}: job {job} has no declared permissions")
    for job in sorted(set(declared["jobs"]) - set(jobs)):
        problems.append(f"{name}: declared job {job} does not exist")
    for job in sorted(set(jobs) & set(declared["jobs"])):
        effective = jobs[job].get("permissions", workflow.get("permissions"))
        if effective != declared["jobs"][job]:
            problems.append(f"{name}: {job} holds {effective}, declared {declared['jobs'][job]}")
    return problems


def test_every_workflow_declares_its_permissions():
    assert sorted(p.name for p in workflow_files()) == sorted(PERMISSIONS)


@pytest.mark.parametrize("name", sorted(PERMISSIONS))
def test_every_job_holds_its_declared_permissions(name):
    assert check_permissions(name, load(WORKFLOWS / name), PERMISSIONS[name]) == []


def test_only_the_attesting_jobs_hold_the_attestation_permissions():
    holders = sorted(
        f"{name}/{job}"
        for name, declared in PERMISSIONS.items()
        for job, granted in declared["jobs"].items()
        # publish-pypi and publish-npm held id-token: write before Phase 43,
        # for trusted publishing; they attest nothing.
        if granted.get("attestations") or (granted.get("id-token") and "publish-" not in job)
    )
    # ci-cd.yml's build only passes them on to images.yml's publish.
    assert holders == ["ci-cd.yml/build", "cli-release.yml/release", "images.yml/publish"]


def test_a_widened_or_new_job_is_named(workflow):
    jobs = dict(workflow["jobs"])
    jobs["lint"] = {**jobs["lint"], "permissions": {**READ, "packages": "write"}}
    jobs["new-job"] = {"runs-on": "ubuntu-latest"}
    problems = check_permissions("ci-cd.yml", {**workflow, "jobs": jobs}, PERMISSIONS["ci-cd.yml"])
    assert problems == [
        "ci-cd.yml: job new-job has no declared permissions",
        "ci-cd.yml: lint holds {'contents': 'read', 'packages': 'write'}, "
        "declared {'contents': 'read'}",
    ]


# Phase 43 (D7, decision 5): what is published is attested, then verified.

#: Each attesting job, the attestation actions it runs, how many
#: `gh attestation verify` calls must follow them in a later step, and the
#: predicate types those calls must name (the SBOM's, by its own).
SBOM_PREDICATE = "--predicate-type https://cyclonedx.org/bom"
ATTESTING = {
    ("images.yml", "publish"): (
        ["actions/attest-build-provenance", "actions/attest-sbom"], 2, [SBOM_PREDICATE]
    ),
    ("cli-release.yml", "release"): (["actions/attest-build-provenance"], 1, []),
}

#: What would let a failed verify pass: an alternative after it, or a step
#: that continues on error.
SOFTENED = re.compile(r"gh attestation verify[^\n]*(\|\||;\s*(true|:)\b)")


def check_attests(
    job: dict, actions: list[str], verifies: int, predicates: list[str] = ()
) -> list[str]:
    steps = job.get("steps", [])
    uses = [str(step.get("uses", "")).split("@")[0] for step in steps]
    problems = []
    last_attest = -1
    for action in actions:
        if action not in uses:
            problems.append(f"no {action} step")
        else:
            last_attest = max(last_attest, uses.index(action))
    verified = sum(
        str(step.get("run", "")).count("gh attestation verify")
        for index, step in enumerate(steps)
        if index > last_attest >= 0
    )
    if verified < verifies:
        problems.append(f"{verified} gh attestation verify after the attestations, want {verifies}")
    for step in steps:
        run = str(step.get("run", ""))
        if "gh attestation verify" not in run:
            continue
        if step.get("continue-on-error"):
            problems.append("a verify step continues on error")
        if SOFTENED.search(run):
            problems.append("a verify can fail without failing the step")
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    for predicate in predicates:
        if "gh attestation verify" not in runs or predicate not in runs:
            problems.append(f"no verify names `{predicate}`")
    return problems


@pytest.mark.parametrize(("name", "job"), sorted(ATTESTING))
def test_what_is_published_is_attested_and_verified(name, job):
    actions, verifies, predicates = ATTESTING[(name, job)]
    assert check_attests(load(WORKFLOWS / name)["jobs"][job], actions, verifies, predicates) == []


@pytest.mark.parametrize(
    "run",
    [
        'gh attestation verify "$image" --repo r || true',
        'gh attestation verify "$image" --repo r || echo failed',
        'gh attestation verify "$image" --repo r; true',
    ],
)
def test_a_verify_that_cannot_fail_is_named(run):
    job = {"steps": [{"uses": f"actions/attest-build-provenance@{CHECKOUT_SHA}"}, {"run": run}]}
    assert check_attests(job, ["actions/attest-build-provenance"], 1) == [
        "a verify can fail without failing the step"
    ]


def test_a_verify_step_that_continues_on_error_is_named():
    job = {
        "steps": [
            {"uses": f"actions/attest-build-provenance@{CHECKOUT_SHA}"},
            {"run": "gh attestation verify x --repo r", "continue-on-error": True},
        ]
    }
    assert check_attests(job, ["actions/attest-build-provenance"], 1) == [
        "a verify step continues on error"
    ]


def test_the_sbom_verify_is_named_by_its_predicate():
    job = {
        "steps": [
            {"uses": f"actions/attest-build-provenance@{CHECKOUT_SHA}"},
            {"uses": f"actions/attest-sbom@{CHECKOUT_SHA}"},
            {"run": "gh attestation verify a --repo r\ngh attestation verify a --repo r"},
        ]
    }
    actions = ["actions/attest-build-provenance", "actions/attest-sbom"]
    assert check_attests(job, actions, 2, [SBOM_PREDICATE]) == [
        f"no verify names `{SBOM_PREDICATE}`"
    ]


def test_a_verify_before_the_attestation_is_named():
    job = {
        "steps": [
            {"run": "gh attestation verify x --repo r"},
            {"uses": f"actions/attest-build-provenance@{CHECKOUT_SHA}"},
        ]
    }
    assert check_attests(job, ["actions/attest-build-provenance"], 1) == [
        "0 gh attestation verify after the attestations, want 1"
    ]
