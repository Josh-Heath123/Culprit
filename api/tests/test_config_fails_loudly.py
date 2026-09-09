"""Phase 26 regression test: no service starts with an unset DB URL.

The defect: `app/auth/config.py`, `app/registry/config.py`,
`app/postmortems/config.py` and `app/incidents/config.py` each fell back
to a hardcoded `postgresql+asyncpg://<role>:<role>-dev-password@...`
connection string when their `*_DATABASE_URL` was unset. A deploy
missing one variable therefore did not fail — it started, and connected
(or tried to) as a least-privilege role using a password committed to
this repository.

Tested by reloading each config module with the variable removed, which
is the closest thing to "start the service without it" that a test can
do: these are module-level reads, so import *is* startup for them.
`api/app/ingest_gateway/config.py` is included even though it never had
a fallback — the acceptance criterion is about every service, and a
later edit could add one.
"""

import importlib
import os
from pathlib import Path

import pytest
from app.env import MissingConfigError, require_env

#: (module path, the variable it must refuse to start without).
CONFIG_MODULES = [
    ("app.auth.config", "AUTH_SERVICE_DATABASE_URL"),
    ("app.registry.config", "REGISTRY_ADMIN_DATABASE_URL"),
    ("app.postmortems.config", "POSTMORTEM_WRITER_DATABASE_URL"),
    ("app.incidents.config", "API_READER_DATABASE_URL"),
    ("app.ingest_gateway.config", "INGEST_GATEWAY_DATABASE_URL"),
]


@pytest.mark.parametrize(
    ("module_path", "variable"), CONFIG_MODULES, ids=[case[1] for case in CONFIG_MODULES]
)
def test_config_module_refuses_to_import_without_its_database_url(
    module_path: str, variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(module_path)
    monkeypatch.delenv(variable, raising=False)

    # KeyError for app/ingest_gateway/config.py's os.environ[...], which
    # already failed loudly before this phase and is left as it was.
    with pytest.raises((MissingConfigError, KeyError)):
        importlib.reload(module)

    # Reloaded again with the variable restored, so a failed module is
    # not left behind for whatever imports it next.
    monkeypatch.undo()
    importlib.reload(module)


@pytest.mark.parametrize(
    ("module_path", "variable"), CONFIG_MODULES, ids=[case[1] for case in CONFIG_MODULES]
)
def test_no_config_module_carries_a_dev_password_fallback(
    module_path: str, variable: str
) -> None:
    """The specific string that made this fail open, asserted absent.

    A source-text check rather than a behavioural one on purpose: the
    behaviour above only catches a fallback on the *one* variable each
    module is parameterised with, and this catches one reintroduced
    anywhere in the file.
    """
    module = importlib.import_module(module_path)
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    # `dev-password@`, not `dev-password`: the marker is the host
    # separator of an actual connection string, so a comment explaining
    # the removed fallback cannot trip it.
    assert "dev-password@" not in source


def test_require_env_treats_an_empty_value_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank line in a `.env`, or an unset shell variable interpolated
    into a compose file, produces `""` — not a configured value."""
    monkeypatch.setenv("CULPRIT_TEST_VARIABLE", "")
    with pytest.raises(MissingConfigError, match="CULPRIT_TEST_VARIABLE"):
        require_env("CULPRIT_TEST_VARIABLE")

    monkeypatch.setenv("CULPRIT_TEST_VARIABLE", "set")
    assert require_env("CULPRIT_TEST_VARIABLE") == "set"


def test_require_env_message_names_the_variable_and_the_hint() -> None:
    os.environ.pop("CULPRIT_ABSENT_VARIABLE", None)
    with pytest.raises(MissingConfigError) as excinfo:
        require_env("CULPRIT_ABSENT_VARIABLE", hint="see infra/.env.prod.example")
    assert "CULPRIT_ABSENT_VARIABLE" in str(excinfo.value)
    assert "infra/.env.prod.example" in str(excinfo.value)
