"""Tests for scripts/check_no_llm_imports.py (Phase 26).

A check that cannot fail is not a check, so most of this file is about
proving it catches things — written against temporary packages rather
than the real ones, since the real ones are (and must stay) clean.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_no_llm_imports import (
    CHAT_LLM_PREFIXES,
    DETERMINISTIC_PACKAGES,
    EMBEDDING_PREFIXES,
    check_package,
    main,
)

STRICT = CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES

ROOT = Path(__file__).resolve().parent.parent.parent


def _package(tmp_path: Path, source: str) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text(source, encoding="utf-8")
    return package


@pytest.mark.parametrize(
    "source",
    [
        "import anthropic",
        "import voyageai",
        "from anthropic import Anthropic",
        "from google.genai import Client",
        "from app.rag.llm import generate_root_cause_analysis",
        "from worker.app.rag import prompts",
        "import openai",
    ],
)
def test_a_forbidden_import_is_caught(tmp_path: Path, source: str) -> None:
    assert check_package(_package(tmp_path, source), STRICT)


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from app.db import raw_events",
        # Prefix matching is on module *boundaries*, not raw string
        # prefixes: a package that merely starts with the same letters
        # is not the forbidden one.
        "import anthropicsaurus",
        "from app.ragtime import x",
    ],
)
def test_an_innocent_import_is_not_caught(tmp_path: Path, source: str) -> None:
    assert check_package(_package(tmp_path, source), STRICT) == []


def test_the_declared_packages_are_actually_clean() -> None:
    """The check, run for real over what it claims to protect."""
    assert main([]) == 0


def test_every_declared_package_that_exists_is_a_directory() -> None:
    """A typo'd path in DETERMINISTIC_PACKAGES silently checks nothing.

    Skipping a not-yet-created package is deliberate (Phase 28's `cli/`
    is listed before it exists), so this asserts the ones that *do*
    exist today are all real, rather than asserting all of them are.
    """
    existing = [name for name in DETERMINISTIC_PACKAGES if (ROOT / name).exists()]
    assert existing, "no declared deterministic package exists — the list is wrong"
    for name in existing:
        assert (ROOT / name).is_dir(), name


def test_an_explicit_missing_package_is_an_error() -> None:
    """Skipping is only for the default list. A path passed on the
    command line that does not exist is a mistake worth failing on."""
    assert main(["definitely/not/a/package"]) == 2


def test_the_forbidden_list_covers_both_llm_providers_this_repo_uses() -> None:
    """`LLM_PROVIDER` switches between Anthropic and Gemini
    (worker/app/rag/providers/); a list covering only one of them would
    pass while the other walked straight through."""
    assert "anthropic" in CHAT_LLM_PREFIXES
    assert "google.genai" in CHAT_LLM_PREFIXES


def test_mcp_server_may_embed_but_may_not_chat() -> None:
    """The one package with a relaxed rule, pinned so the relaxation
    cannot quietly widen.

    `mcp_server/tools.py` embeds a query to search engineering memory,
    which is why `voyageai` is not forbidden there;
    `mcp_server/tests/test_no_llm_chat_calls.py` is what proves the
    client is only ever `.embed()`-ed. Every chat client stays banned.
    """
    allowed = DETERMINISTIC_PACKAGES["mcp_server"]
    assert set(CHAT_LLM_PREFIXES) <= set(allowed)
    assert not set(EMBEDDING_PREFIXES) & set(allowed)


def test_every_other_package_forbids_embedding_too() -> None:
    for name, forbidden in DETERMINISTIC_PACKAGES.items():
        if name == "mcp_server":
            continue
        assert set(EMBEDDING_PREFIXES) <= set(forbidden), name


def test_a_vendored_virtualenv_is_not_scanned(tmp_path: Path) -> None:
    """A package containing a `.venv` must not report its dependencies'
    imports. `mcp_server` has one, and without this the check drowns in
    third-party hits and gets switched off."""
    package = tmp_path / "pkg"
    vendored = package / ".venv" / "Lib" / "site-packages" / "thirdparty"
    vendored.mkdir(parents=True)
    (vendored / "mod.py").write_text("import anthropic", encoding="utf-8")
    (package / "module.py").write_text("import json", encoding="utf-8")

    assert check_package(package, STRICT) == []
