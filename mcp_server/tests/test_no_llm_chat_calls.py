"""Structural proof of invariant 8 (docs/AI_NATIVE_PLAN.md §1) and this
phase's own Out of scope ("Any tool that calls an LLM itself"): no tool
implementation in mcp_server/tools.py calls anything on the Voyage client
except `.embed(...)` (via `_embed_query`) -- never a chat/completion
endpoint, and no `anthropic`/`google.generativeai` import at all. Same
style of structural proof scripts/tests/test_no_llm_imports.py (Phase 22)
and worker/tests/test_link_job.py's own import-boundary test already
give their own invariants, applied here to invariant 8's MCP-tool case.
"""

import ast
from pathlib import Path

TOOLS_PATH = Path(__file__).resolve().parent.parent / "tools.py"

FORBIDDEN_IMPORT_PREFIXES = ("anthropic", "google.generativeai")


def _tree() -> ast.Module:
    return ast.parse(TOOLS_PATH.read_text(), filename=str(TOOLS_PATH))


def test_tools_module_has_no_chat_llm_import() -> None:
    tree = _tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(
        name.startswith(prefix) for name in imported for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_voyage_client_only_ever_calls_embed() -> None:
    """Walks every attribute-access chain rooted at a call to
    `_get_voyage_client()` and asserts the only method ever called on it
    is `.embed(...)` -- not `.chat(...)`, `.generate(...)`, or any other
    Voyage SDK surface a future edit might reach for."""
    tree = _tree()
    voyage_client_call_methods: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Matches `_get_voyage_client().<method>(...)` -- the only shape
        # this module ever uses to reach the Voyage client.
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Call)
            and isinstance(func.value.func, ast.Name)
            and func.value.func.id == "_get_voyage_client"
        ):
            voyage_client_call_methods.add(func.attr)

    assert voyage_client_call_methods == {"embed"}
