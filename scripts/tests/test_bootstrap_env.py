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

import os
import stat
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
    """A non-local build_env() prompts for VOYAGE_API_KEY.
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


def test_the_local_quickstart_answers_an_agent_on_this_machine() -> None:
    """An agent in a container reaches the quickstart through the host as
    host.docker.internal; Caddy answers only the site addresses in DOMAIN,
    so that name has to be one (Phase 33 part 2). A real install's domain
    is left exactly as given."""
    local = _build(domain="localhost", local=True)
    assert local["DOMAIN"] == "http://localhost, http://host.docker.internal"
    real = _build(domain="culprit.example.com", local=False)
    assert real["DOMAIN"] == "culprit.example.com"


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
        "CAPTURE_WRITER_DB_PASSWORD",
        "PROBE_WRITER_DB_PASSWORD",
        "INVESTIGATION_WRITER_DB_PASSWORD",
        "AGENT_ADMIN_DB_PASSWORD",
        "AGENT_REGISTRAR_DB_PASSWORD",
        "AGENT_GATEWAY_DB_PASSWORD",
        "VERIFICATION_WRITER_DB_PASSWORD",
        "NARRATOR_DB_PASSWORD",
        "MCP_READER_DB_PASSWORD",
        "INVENTORY_DB_PASSWORD",
    ],
)
def test_every_role_password_is_generated(variable: str) -> None:
    """Phase 26 made the matching `*_DATABASE_URL` reads fail loudly with
    no fallback, so a role whose password bootstrap_env forgets is now a
    container that will not start."""
    env = _build(domain="example.com", local=False)
    assert env[variable], f"{variable} was not generated"


# --- Q18: infra/.env.prod is never readable by anyone but its owner -------
#
# The file holds every secret in clear text by design (DIAGNOSTIC_PLAN.md,
# Q18). What it must never do is exist, even for a moment, with a mode that
# lets another local user read it. It used to: write_text() created it with
# the umask's mode (0644 under the usual 022) and chmod(0o600) came after.
#
# The test does not assume how the file is written. A Python audit hook
# fires on every filesystem event the process raises (open, chmod, rename,
# mkstemp, ...); at each one, every file in the output directory is
# stat()ed, and any mode with a group or other bit is recorded. Audit hooks
# cannot be removed, so one is installed per process and is inert unless a
# test has pointed it at a directory.

_WATCH: dict = {"dir": None, "busy": False, "seen": [], "untouched": None, "events": set()}
_HOOK_INSTALLED = False


def _audit(event: str, args: tuple) -> None:
    directory = _WATCH["dir"]
    if directory is None or _WATCH["busy"]:
        return
    _WATCH["events"].add(event)
    _WATCH["busy"] = True  # the scan below raises audit events of its own
    try:
        for entry in os.scandir(directory):
            try:
                mode = stat.S_IMODE(entry.stat(follow_symlinks=False).st_mode)
            except FileNotFoundError:
                continue  # removed between the listing and the stat
            if mode & 0o077 and not _is_untouched(entry):
                _WATCH["seen"].append((event, entry.name, oct(mode)))
    finally:
        _WATCH["busy"] = False


def _is_untouched(entry: os.DirEntry) -> bool:
    """The world-readable file a test planted on purpose, still holding
    exactly what it was planted with. Once anything writes to it, it counts."""
    untouched = _WATCH["untouched"]
    if untouched is None or entry.name != untouched[0]:
        return False
    try:
        with open(entry.path, "rb") as f:
            return f.read() == untouched[1]
    except FileNotFoundError:
        return False


@pytest.fixture
def watched_dir(tmp_path: Path):
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_audit)
        _HOOK_INSTALLED = True
    # 022 is the usual default and the one under which the old code leaked
    # a 0644 file; set it so the result does not depend on the runner's.
    old_umask = os.umask(0o022)
    _WATCH.update(dir=str(tmp_path), seen=[], untouched=None, events=set())
    try:
        yield tmp_path
    finally:
        _WATCH.update(dir=None, untouched=None)
        os.umask(old_umask)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes do not apply on Windows")
@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "force-over-0644"])
def test_env_prod_never_exists_with_wider_permissions(
    watched_dir: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    """At no filesystem event during main() is any file in infra/ wider than
    0600, and the result is 0600 with no temporary file left behind. The
    second case is --force over an existing world-readable file: its mode
    must not be relied on, nor the new secrets written into it."""
    target = watched_dir / ".env.prod"
    if existing:
        _WATCH["dir"] = None  # setting up the precondition is not the code under test
        target.write_bytes(b"OLD=1\n")
        target.chmod(0o644)
        _WATCH.update(dir=str(watched_dir), untouched=(target.name, b"OLD=1\n"))
    monkeypatch.setattr(bootstrap_env, "ENV_PROD_PATH", target)
    monkeypatch.setattr(sys, "argv", ["bootstrap_env.py", "--local", "--force"])

    assert bootstrap_env.main() == 0
    _audit("final", ())  # one last look after main() returns

    # Not vacuous: the hook was live while main() wrote the file.
    assert "open" in _WATCH["events"], f"audit hook saw no file being opened: {_WATCH['events']}"
    assert _WATCH["seen"] == [], f"secrets file was readable beyond its owner: {_WATCH['seen']}"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    leftover = [p.name for p in watched_dir.iterdir()]
    assert leftover == [".env.prod"], f"a temporary file was left behind: {leftover}"
    assert "JWT_SECRET_KEY=" in target.read_text()


def test_the_demo_database_password_is_generated_not_written() -> None:
    """Phase 37 part 1 close-out: the demo's own database had a fixed
    password in the compose file. Every use now reads the generated one."""
    compose = (ROOT / "infra" / "docker-compose.quickstart.yml").read_text(encoding="utf-8")
    urls = [line for line in compose.splitlines() if "INVENTORY_DATABASE_URL:" in line]
    assert len(urls) == 2
    for line in urls:
        assert "postgresql://inventory:${INVENTORY_DB_PASSWORD:-}@" in line, line
    assert "not-a-secret@" not in compose
