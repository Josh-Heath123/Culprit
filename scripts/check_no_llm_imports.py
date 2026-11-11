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
    # Phase 35 part 2: the narrator is this repo's one route to a model now.
    "app.narrate",
    "worker.app.narrate",
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
    # Phase 28. `.claude/rules/determinism.md` names "fact extraction"
    # explicitly, and this is it: the extractor plugins produce every
    # INTENT fact in the system. An LLM anywhere in this path would mean
    # a *fact* was invented rather than read, which is the one thing D8
    # forbids outright.
    "extractors/python": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
    # Phase 35 part 2. The API serves narrations and runs the narration
    # check again before it does; it never calls a provider. Only the
    # worker's app.narrate may (worker/pyproject.toml's contracts).
    "api/app": CHAT_LLM_PREFIXES + EMBEDDING_PREFIXES,
}

#: Go module paths for every LLM/embedding SDK a Go program could
#: plausibly reach. Kept deliberately broad: the cost of a false positive
#: is a five-second conversation, the cost of a miss is a narration call
#: inside the extraction layer passing CI.
#:
#: `github.com/google/generative-ai-go` is the one that matters most and
#: was missing from the first version of this list — `LLM_PROVIDER=gemini`
#: is this repository's own production default, so it is the single most
#: likely import to appear. (Found by the Phase 28 invariant audit.)
_GO_LLM_MODULES = (
    "github.com/anthropics",
    "github.com/sashabaranov/go-openai",
    "github.com/google/generative-ai-go",
    "google.golang.org/genai",
    "github.com/tmc/langchaingo",
    "github.com/cohere-ai/cohere-go",
    "github.com/ollama/ollama",
    "github.com/openai/openai-go",
)

_JS_LLM_MODULES = (
    "@anthropic-ai/",
    "openai",
    "@google/generative-ai",
    "@google/genai",
    "langchain",
    "cohere-ai",
    "voyageai",
)

#: Go and JavaScript packages held to the same rule.
#:
#: A separate list because the check below is a Python AST walk and
#: cannot parse either language. These are scanned as *source text* for
#: an import of a known LLM SDK — coarser than the AST walk, and enough:
#: importing a client is the observable act, and there is no way to reach
#: one of these SDKs in Go or JavaScript without naming it in an import.
#:
#: `cli/internal/extract` and `cli/internal/model` are named in
#: determinism.md; `extractors/node` is the JavaScript half of the same
#: extraction layer.
NON_PYTHON_DETERMINISTIC_PACKAGES: dict[str, tuple[str, ...]] = {
    # Every first-party Go package, `cmd` included. `cli/internal` alone
    # left cli/cmd/culprit/main.go covered by nothing, which is the
    # blind spot standing invariant 9 exists to catch — found by the
    # Phase 28 invariant audit.
    "cli": _GO_LLM_MODULES,
    "extractors/node": _JS_LLM_MODULES,
}

#: File extensions scanned in those packages.
#:
#: `.cjs` and `.cts` matter more than they look: extractors/node's
#: package.json is `"type": "module"`, so `.cjs` is the *natural*
#: extension for any CommonJS file added there — and a
#: `require("openai")` in one was invisible to the first version of this
#: list. Found by the Phase 28 invariant audit.
NON_PYTHON_SUFFIXES = (".go", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")

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


def check_non_python_package(package_dir: Path, forbidden: tuple[str, ...]) -> list[str]:
    """Source-text scan for an LLM SDK import in Go or JavaScript.

    Coarser than the AST walk above, and deliberately so: this script has
    no Go or JavaScript parser, and adding one to check a handful of
    import lines would be a poor trade. It is also enough — importing a
    client is the observable act, and neither language offers a way to
    reach one of these SDKs without naming it in an import or a require,
    which is the string this looks for.

    Its limit is the one the Python side already documents: a fully
    dynamic import with a computed name is invisible to it. Nothing in
    this repository imports dynamically, and the boundary is enforced at
    review time and by `worker`'s import-linter contracts as well.
    """
    errors: list[str] = []
    for path in sorted(package_dir.rglob("*")):
        if path.suffix not in NON_PYTHON_SUFFIXES or not path.is_file():
            continue
        if not SKIPPED_DIRECTORY_NAMES.isdisjoint(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - unreadable file
            continue
        is_go = path.suffix == ".go"
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # **Go is scanned line for line, with no import-shape
            # narrowing.** The first version of this required a line to
            # start with `import ` (or a quote, or contain ` from `),
            # which the gofmt-canonical form defeats outright:
            #
            #     import (
            #         oai "github.com/sashabaranov/go-openai"
            #     )
            #
            # That inner line starts with an identifier, not `import`,
            # and was skipped. The audit demonstrated it passing. A Go
            # import path can only be written as a quoted string, so
            # matching the module path anywhere is both sufficient and
            # nearly false-positive-free — a comment naming one is the
            # only way to trip it, and this file's own prose lives in
            # Python, not Go.
            #
            # JavaScript keeps the narrowing: `openai` is a plausible
            # substring of ordinary prose and identifiers there, and
            # `import`/`require`/`from` genuinely disambiguate.
            if not is_go:
                is_import_shaped = (
                    stripped.startswith(
                        ("import ", "import(", "from ", "require(", "const ", "let ", "var ")
                    )
                    or stripped.startswith(("'", '"'))
                    or " from " in stripped
                    or "require(" in stripped
                    or "import(" in stripped
                )
                if not is_import_shaped:
                    continue
                # A line comment is not an import in either language.
                if stripped.startswith(("//", "*", "/*")):
                    continue
            elif stripped.startswith(("//", "*", "/*")):
                continue
            for forbidden_name in forbidden:
                if forbidden_name in stripped:
                    errors.append(
                        f"{_display(path)}:{number}: imports {forbidden_name!r}, "
                        "forbidden in a deterministic package"
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

    # Go and JavaScript. Skipped when the caller named specific packages
    # on the command line, since those are always Python directories
    # passed by a hook that just saw a .py file change.
    if not argv:
        for name, forbidden_names in NON_PYTHON_DETERMINISTIC_PACKAGES.items():
            package_dir = ROOT / name
            if not package_dir.is_dir():
                continue
            checked.append(name)
            errors.extend(check_non_python_package(package_dir, forbidden_names))

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
