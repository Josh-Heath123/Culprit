"""Phase 26 regression test: the worker refuses to start without its DB URLs.

The api-side twin of this file is `api/tests/test_config_fails_loudly.py`;
see it for the defect being regressed. `app/main.py` had the same four
`<role>-dev-password` fallbacks, and the phase's acceptance criterion is
about *every* service, not only the four api modules its plan section
happens to name.

`app.main` is reloaded rather than imported fresh because importing it
also configures observability and imports every job module — reload is
enough to re-run the module-level config reads, which is where startup
actually fails.
"""

import importlib
from pathlib import Path

import pytest
from app.env import MissingConfigError, require_env

WORKER_DATABASE_URLS = [
    "DATABASE_URL",
    "ANOMALY_DATABASE_URL",
    "CORRELATION_DATABASE_URL",
    "ROOT_CAUSE_DATABASE_URL",
    # Phase 31. Fifth, and required for the same reason as the other
    # four: a worker that starts without it would score metrics and
    # silently write no readings, which looks like "nothing to report".
    "PROBE_WRITER_DATABASE_URL",
    # Phase 35 part 2: required even with narration off, so turning it on
    # later is a setting, not a missing credential.
    "NARRATOR_DATABASE_URL",
]


@pytest.mark.parametrize("variable", WORKER_DATABASE_URLS)
def test_worker_refuses_to_start_without_its_database_urls(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = importlib.import_module("app.main")
    monkeypatch.delenv(variable, raising=False)

    # load_dotenv() runs at the top of app/main.py and would put a real
    # worker/.env value straight back; point it at nothing so this test
    # is about the environment it was given, not the developer's disk.
    monkeypatch.setattr("app.main.load_dotenv", lambda *args, **kwargs: False)

    with pytest.raises(MissingConfigError, match=variable):
        importlib.reload(main)

    monkeypatch.undo()
    importlib.reload(main)


def test_worker_main_carries_no_dev_password_fallback() -> None:
    main = importlib.import_module("app.main")
    assert main.__file__ is not None
    source = Path(main.__file__).read_text(encoding="utf-8")
    # `dev-password@`, not `dev-password`: the marker is the host
    # separator of an actual connection string, so this file's own prose
    # about the removed fallback cannot trip it.
    assert "dev-password@" not in source


def test_require_env_treats_an_empty_value_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CULPRIT_TEST_VARIABLE", "")
    with pytest.raises(MissingConfigError, match="CULPRIT_TEST_VARIABLE"):
        require_env("CULPRIT_TEST_VARIABLE")
