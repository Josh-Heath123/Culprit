"""The narrator's two `lint-imports` contracts cover every package — Phase 35
part 2, standing invariant 9.

A forbidden contract checks only the source modules it names. A package
added to app/ tomorrow and not named would be free to import a provider
client, or to read a narration, with the contract still green. This fails
first: every module and package under app/ except app.narrate itself and
app.main (which only schedules the job) must be a source of both.
"""

import tomllib
from pathlib import Path

WORKER = Path(__file__).resolve().parent.parent
CONTRACTS = ("only the narrator talks to a provider", "nothing downstream reads a narration")
EXEMPT = {"app.narrate", "app.main"}


def _contract(name: str) -> dict:
    config = tomllib.loads((WORKER / "pyproject.toml").read_text(encoding="utf-8"))
    for contract in config["tool"]["importlinter"]["contracts"]:
        if contract["name"] == name:
            return contract
    raise AssertionError(f"no contract named {name!r}")


def _app_modules() -> set[str]:
    found = set()
    for path in (WORKER / "app").iterdir():
        if path.is_dir() and (path / "__init__.py").exists():
            found.add(f"app.{path.name}")
        elif path.suffix == ".py" and path.stem != "__init__":
            found.add(f"app.{path.stem}")
    return found - EXEMPT


def test_every_package_is_a_source_of_both_contracts() -> None:
    modules = _app_modules()
    assert "app.anomaly" in modules and "app.rag" in modules  # the walk found app/
    for name in CONTRACTS:
        sources = set(_contract(name)["source_modules"])
        missing = modules - sources
        assert not missing, f"{name}: {sorted(missing)} not named as a source"
        assert "culprit_model" in sources


def test_the_contracts_forbid_what_they_say() -> None:
    assert {"httpx", "anthropic"} <= set(_contract(CONTRACTS[0])["forbidden_modules"])
    assert _contract(CONTRACTS[1])["forbidden_modules"] == ["app.narrate"]
