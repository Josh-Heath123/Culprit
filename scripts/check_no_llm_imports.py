#!/usr/bin/env python3
"""Fails if a package declared deterministic imports an LLM client.

Phase 26 (docs/DIAGNOSTIC_PLAN.md field 4). Generalises the AST test
`mcp_server/tests/test_no_llm_chat_calls.py` already applies to one file
into a check over a configured list of packages, so that
`.claude/rules/determinism.md`'s list of "deterministic — no LLM call,
ever" modules is enforced structurally instead of by memory.

Why this and not `lint-imports`: import-linter works on a package graph
rooted in one installed project, and the packages that must stay
deterministic live across four uv projects (`worker/`, `api/`,
`shared/`, `scripts/`, and `cli/` from Phase 28). This is a plain AST
walk over source files, so it needs nothing installed and holds for a
package that has no venv of its own.

What it catches: an `import anthropic`, a `from voyageai import ...`, a
`from app.rag import ...` — anywhere in a declared package, with each
package declaring which of those it may not use (`mcp_server` may embed
and may not chat; everything else may do neither). What it does
not catch: a dynamic `importlib.import_module(name)` with a computed
name. That is a real limit, stated rather than papered over; the
determinism boundary is also enforced at review time and by
`worker`'s own import-linter contracts, and nothing in this codebase
imports dynamically.

Usage:
    check_no_llm_imports.py [PACKAGE_DIR ...]

With no arguments, checks DETERMINISTIC_PACKAGES below. A package listed
there that does not exist yet is skipped, not an error — the list names
packages this plan will create (cli/internal/... in Phase 28), and a
check that fails before its subject exists is a check people learn to
ignore.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Chat/completion clients, and this repo's own route to one. Nothing
#: deterministic may import any of these, ever.
CHAT_LLM_PREFIXES = (
    "anthropic",
    "google.genai",
    "google.generativeai",
    "openai",
    "app.rag",
    "worker.app.rag",
)

#: The embedding client, kept separate on purpose. Embedding is a
#: deterministic-enough operation that `mcp_server` is allowed it (its
#: semantic search over engineering memory needs vectors), and
#: `mcp_server/tests/test_no_llm_chat_calls.py` proves the client is only
#: ever `.embed()`-ed there. Every other package below forbids it too:
#: canonicalisation and anomaly scoring have no business embedding
#: anything, and reaching for a vector is how "just ask the model" starts.
EMBEDDING_PREFIXES = ("voyageai",)

#: Package -> the import prefixes it may not use. Kept in step with
#: `.claude/rules/determinism.md` — that file is the prose, this is the
#: enforcement. Add a package here in the same commit that creates it
#: (docs/DIAGNOSTIC_PLAN.md §3, standing invariant 6). A package listed
#: here that does not exist yet is skipped rather than failing: the list
#: names packages this plan will create (`cli/internal/...` in Phase 28),
#: and a check that fails before its subject exists is a check people
#: learn to ignore.
DETERMINISTIC_PACKAGES: dict[str, tuple[str, ...]] = {
    "shared/culprit_model": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    "shared/culprit_shared": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    "worker/app/anomaly": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    "worker/app/correlation": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    "scripts": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    # `.claude/rules/determinism.md` names "the MCP tool implementations"
    # explicitly. It may embed and may not chat — see EMBEDDING_PREFIXES.
    "mcp_server": CHAT_LLM_PREFIXES,
}

#: Directories that are never this repo's code. `.venv` matters: a
#: package with a virtualenv inside it would otherwise report every
#: third-party module its own dependencies import, which is both wrong
#: and loud enough to get the check disabled.
SKIPPED_DIRECTORY_NAMES = {"__pycache__", ".venv", "node_modules", "site-packages", ".git"}


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise — a package
    directory passed on the command line need not live under ROOT."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def check_package(package_dir: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        if not SKIPPED_DIRECTORY_NAMES.isdisjoint(path.parts):
            continue
        for imported in sorted(_imported_module_names(path)):
            for forbidden in forbidden_prefixes:
                # Module-boundary match, not a raw string prefix:
                # `anthropicsaurus` is not `anthropic`.
                if imported == forbidden or imported.startswith(forbidden + "."):
                    errors.append(
                        f"{_display(path)}: imports {imported!r}, "
                        f"forbidden in a deterministic package"
                    )
    return errors


def main(argv: list[str]) -> int:
    # A package named on the command line is held to the strictest rule
    # set, since there is no declaration saying otherwise.
    packages = (
        {name: CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES for name in argv}
        if argv
        else DETERMINISTIC_PACKAGES
    )

    errors: list[str] = []
    checked: list[str] = []
    for name, forbidden_prefixes in packages.items():
        package_dir = ROOT / name
        if not package_dir.is_dir():
            if argv:
                print(f"No such package directory: {name}", file=sys.stderr)
                return 2
            continue
        checked.append(name)
        errors.extend(check_package(package_dir, forbidden_prefixes))

    if errors:
        print("LLM client imported from a deterministic package:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nSee .claude/rules/determinism.md. If a change genuinely needs to cross "
            "this boundary, that is the signal the rule is about to be broken — not a "
            "list to shorten.",
            file=sys.stderr,
        )
        return 1

    print(f"No LLM imports in {len(checked)} deterministic package(s): {', '.join(checked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
