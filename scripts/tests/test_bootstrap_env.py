"""Phase 26 regression test: bootstrap_env writes the real image path.

The defect: `scripts/bootstrap_env.py` still emitted
`IMAGE_REGISTRY=ghcr.io/josh-heath123/view` after the repository was
renamed from `View` to `Culprit` in Phase 20. Every non-local
`just bootstrap-env` therefore produced a `.env.prod` whose
`docker compose pull` reached for images that do not exist — the exact
first-run failure the rename was supposed to remove.

A generated `.env.prod` is the one artefact a new install is built on, so
the assertions below are about what it actually contains, not about the
function's internals.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap_env  # noqa: E402

#: Where the images have lived since Phase 20 — matches
#: infra/docker-compose.prod.yml's own `${IMAGE_REGISTRY:-...}` default
#: and .github/workflows/ci-cd.yml's push target.
EXPECTED_REGISTRY = "ghcr.io/josh-heath123/culprit"


@pytest.fixture(autouse=True)
def _no_prompting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-local build_env() prompts for LLM_PROVIDER and API keys.
    Answering with the offered default is what a real operator pressing
    Enter does, and it keeps this file about the generated values rather
    than about the prompt loop."""
    monkeypatch.setattr(
        bootstrap_env, "_prompt", lambda label, *, default=None, secret=False: default or ""
    )


def _build(**kwargs) -> dict:
    env, _password = bootstrap_env.build_env(**kwargs)
    return env


def test_a_real_install_points_at_the_culprit_image_path() -> None:
    env = _build(domain="example.com", local=False)
    assert env["IMAGE_REGISTRY"] == EXPECTED_REGISTRY
    assert "view" not in env["IMAGE_REGISTRY"]


def test_the_local_quickstart_builds_rather_than_pulls() -> None:
    """`--local` leaves both blank on purpose: the quickstart compose
    builds every image from the working tree, so a registry path there
    would be a pull that should never happen."""
    env = _build(domain="localhost", local=True)
    assert env["IMAGE_REGISTRY"] == ""
    assert env["IMAGE_TAG"] == ""


def test_the_generated_registry_matches_the_compose_default() -> None:
    """If these two ever disagree, one of them is pulling images nobody
    publishes — and the compose default is the one a user who never runs
    bootstrap_env falls back to."""
    compose = (ROOT / "infra" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert f"${{IMAGE_REGISTRY:-{EXPECTED_REGISTRY}}}" in compose


@pytest.mark.parametrize(
    "variable",
    [
        "REGISTRY_ADMIN_DB_PASSWORD",
        "AUTH_SERVICE_DB_PASSWORD",
        "POSTMORTEM_WRITER_DB_PASSWORD",
        "FACT_WRITER_DB_PASSWORD",
        "MCP_READER_DB_PASSWORD",
    ],
)
def test_every_role_password_is_generated(variable: str) -> None:
    """Phase 26 made the matching `*_DATABASE_URL` reads fail loudly with
    no fallback, so a role whose password bootstrap_env forgets is now a
    container that will not start."""
    env = _build(domain="example.com", local=False)
    assert env[variable], f"{variable} was not generated"
