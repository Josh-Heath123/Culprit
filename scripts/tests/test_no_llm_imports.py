"""Structural proof of invariant 8 (docs/AI_NATIVE_PLAN.md §1): none of
Phase 22's deterministic-check scripts import an LLM/embedding client,
for the same reason `lint-imports` already enforces invariant 1
(worker/app/anomaly <-> worker/app/rag isolation) structurally rather
than by convention -- a hook that could reach an LLM client is exactly
the failure mode .claude/rules/determinism.md
rules out for this whole plan.

check_invariants.sh (bash, not Python) is checked by substring search
over its raw text instead of ast import parsing -- it never `import`s
anything, but it could in principle call out to something LLM-shaped,
so the same forbidden-name list is asserted absent from its source.
"""

import ast
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = SCRIPTS_DIR.parent / ".claude" / "hooks" / "check_invariants.sh"

FORBIDDEN_PREFIXES = ("anthropic", "voyageai", "google.generativeai", "worker.app.rag", "app.rag")


def _python_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_check_migration_symmetry_has_no_llm_import() -> None:
    imports = _python_imports(SCRIPTS_DIR / "check_migration_symmetry.py")
    assert not any(
        imported.startswith(forbidden) for imported in imports for forbidden in FORBIDDEN_PREFIXES
    )


def test_check_coupled_files_has_no_llm_import() -> None:
    imports = _python_imports(SCRIPTS_DIR / "check_coupled_files.py")
    assert not any(
        imported.startswith(forbidden) for imported in imports for forbidden in FORBIDDEN_PREFIXES
    )


def test_check_invariants_hook_has_no_llm_reference() -> None:
    text = HOOK_SCRIPT.read_text()
    for forbidden in FORBIDDEN_PREFIXES:
        assert forbidden not in text
