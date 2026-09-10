"""The self-check's placeholder environment must be the same everywhere.

`api/app/*/config.py` reads several variables at import time and refuses
to import without them (Phase 26 removed the fail-open dev-password
fallbacks deliberately). Introspecting a FastAPI app means importing it,
so without those variables `culprit-extract-python` reports
`KeyError: JWT_SECRET_KEY` and skips `http_routes` and `db_schema` — the
two rank-90 *enumerating* sources, and the ones acceptance criteria 1, 2
and 4 depend on.

The result is not an error. It is `culprit check` reporting
`No divergences` over a fact set with the route table and the ORM schema
missing: a confident, meaningless zero. That is this product's own
failure mode — "nothing found" that means "nothing looked" — and it
shipped in Culprit's own dogfooding gate until the Phase 29 audit caught
it. Supplying the environment took the self-check from 484 facts to 983.

The values therefore live in two places that cannot be made one: a
`justfile` recipe, and a GitHub Actions `env:` block. This test parses
both and fails if they diverge — the same technique, and the same
reasoning, as `test_scan_coverage.py`'s check on the stop hook's
exclusion list. The copy that *runs in CI* is the one that has to be
right.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "justfile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci-cd.yml"

#: The recipe that owns the values locally.
RECIPE = "_self-check-env"


def _justfile_env() -> dict[str, str]:
    """The variables `_self-check-env` exports.

    Handles both forms the recipe uses: a plain `export NAME=value` and
    the `for name in ...; do export "${name}_DATABASE_URL=..."` loop,
    which is expanded here rather than executed.
    """
    text = JUSTFILE.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(RECIPE)} \*ARGS:\n(.*?)(?=\n[^\s#]|\Z)",
        text,
        re.S | re.M,
    )
    assert match, f"the justfile has no `{RECIPE}` recipe to check"
    body = match.group(1)

    env: dict[str, str] = {}
    for name, value in re.findall(r'^\s*export ([A-Z_]+)=(\S+)', body, re.M):
        env[name] = value

    loop = re.search(
        r"for name in ([A-Z_ ]+); do\s*\n\s*export \"\$\{name\}_DATABASE_URL=(\S+)\"",
        body,
    )
    if loop:
        for prefix in loop.group(1).split():
            env[f"{prefix}_DATABASE_URL"] = loop.group(2)

    assert env, f"parsed no environment out of `{RECIPE}` — the parser is stale"
    return env


def _workflow_self_check_envs() -> list[tuple[str, dict[str, str]]]:
    """Every step of the `self-check` job that runs `culprit check`."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"].get("self-check")
    assert job, "ci-cd.yml has no `self-check` job"

    steps = []
    for step in job["steps"]:
        if "culprit check" in str(step.get("run", "")):
            steps.append((step.get("name", "<unnamed>"), step.get("env") or {}))
    assert steps, "the self-check job runs `culprit check` nowhere"
    return steps


def test_every_ci_self_check_step_sets_the_same_environment() -> None:
    expected = _justfile_env()
    for name, env in _workflow_self_check_envs():
        missing = sorted(set(expected) - set(env))
        assert not missing, (
            f"CI step {name!r} is missing {missing}. Without them the extractor "
            f"skips http_routes and db_schema and the job reports a meaningless "
            f"zero. Keep it in step with the justfile's `{RECIPE}` recipe."
        )
        for key, value in expected.items():
            assert env[key] == value, (
                f"CI step {name!r} sets {key}={env[key]!r}, the justfile sets "
                f"{value!r}"
            )


def test_the_local_recipes_all_go_through_the_shared_env() -> None:
    """No self-check recipe may invoke the binary directly.

    That is how the drift happened: `self-check` called `go run` itself
    while `intent` carried the environment, so the two commands read the
    same repository and saw different systems.
    """
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in ("self-check", "self-check-sarif", "self-check-coverage"):
        match = re.search(
            rf"^{re.escape(recipe)}( \*ARGS)?:\n((?:[ \t]+.*\n?)*)",
            text,
            re.M,
        )
        assert match, f"the justfile has no `{recipe}` recipe"
        body = match.group(2)
        assert "go run" not in body, (
            f"`{recipe}` invokes the binary directly instead of going through "
            f"`{RECIPE}`, so it runs without the placeholder environment and "
            "reports a zero that means nothing was extracted"
        )
        assert RECIPE in body, f"`{recipe}` does not go through `{RECIPE}`"


@pytest.mark.parametrize("required", ["JWT_SECRET_KEY", "AGENT_AUTOMATION_TOKEN"])
def test_the_variables_that_actually_break_the_import_are_present(required: str) -> None:
    """Named individually, because these two are the ones that fail.

    `api/app/auth/config.py` and `api/app/memory/config.py` read them at
    module scope with `os.environ[...]`, so a missing one is an immediate
    KeyError during app import — not a degraded run, a skipped want.
    """
    assert required in _justfile_env()
