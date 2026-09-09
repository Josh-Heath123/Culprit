#!/usr/bin/env python3
"""Fails if a migration's upgrade()/downgrade() aren't structurally
symmetric (Phase 22, docs/AI_NATIVE_PLAN.md). Purely static -- parses
each file with Python's `ast` module, no alembic import and no DB
connection, so this can run on every save via a Claude Code hook
(.claude/hooks/check_invariants.sh) as well as in CI.

Deliberately structural, not semantic (see that phase's own Steps): it
cannot prove a downgrade() actually *works* -- only a real `alembic
downgrade` run does that (every phase's own Rollback verification step
in docs/SELF_HOSTED_PLAN.md). It catches the much more common mistake
of a migration author forgetting the downgrade half of a change
entirely, or misnaming a table/column between the two functions. Three
things are checked, matching every real pattern this project's own
migrations under api/migrations/versions/ actually use (verified
against all of them, not just a hypothetical shape):

1. Every `op.create_table("x", ...)` in upgrade() has a matching
   `op.drop_table("x")` in downgrade().
2. Every `op.add_column("t", sa.Column("c", ...))` in upgrade() has a
   matching `op.drop_column("t", "c")` in downgrade().
3. Every `op.execute(...)` in upgrade() whose (statically resolved) SQL
   text matches `GRANT ... TO "<role>"` has a corresponding
   `REVOKE ... FROM "<role>"` or `DROP ROLE ... "<role>"` somewhere in
   downgrade().

Usage:
    check_migration_symmetry.py [FILE ...]

With no arguments, checks every migration file changed vs. `main` (`git
diff --name-only main...HEAD -- api/migrations/versions/`) *and* every
uncommitted one (`git status --porcelain`) -- for local,
non-hook use (`just check-invariants`). A Claude Code hook always passes
the single just-edited file explicitly instead (see check_invariants.sh
-- no reason to run a git diff on every keystroke when the hook already
knows exactly which file changed). CI passes its own explicit file list
computed against `origin/main...HEAD`, not this script's own `main...
HEAD` default, since a CI runner's checkout has no local `main` ref.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parent.parent

# .search()'d against a single op.execute(...) call's resolved text --
# DOTALL so a GRANT/REVOKE statement split across a multi-line string
# still matches as one line.
_GRANT_TO_RE = re.compile(r'GRANT\s.+?\sTO\s+"([^"]+)"', re.IGNORECASE | re.DOTALL)
_REVOKE_FROM_RE = re.compile(r'REVOKE\s.+?\sFROM\s+"([^"]+)"', re.IGNORECASE | re.DOTALL)
_DROP_ROLE_RE = re.compile(r'DROP\s+ROLE\s+(?:IF\s+EXISTS\s+)?"([^"]+)"', re.IGNORECASE)

# A FormattedValue whose expression isn't a resolvable module-level
# string constant (e.g. cc323b6c7779's `", ".join(READABLE_TABLES)`)
# renders as this instead of crashing -- a character that can never
# appear inside a real role name, so it simply can't accidentally
# satisfy _GRANT_TO_RE/_REVOKE_FROM_RE by coincidence.
_UNRESOLVED = "\x00"


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Simple `NAME = "literal"` assignments at module level -- every
    real migration's role-name constant (e.g. `POSTMORTEM_WRITER =
    "postmortem-writer"`) looks exactly like this; nothing here needs to
    resolve tuples, f-strings, or anything computed."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _resolve_string_expr(node: ast.expr, constants: dict[str, str]) -> str | None:
    """Best-effort static resolution of a string expression to its
    literal text. Handles a plain string constant and an f-string
    (ast.JoinedStr) whose `{...}` parts are bare Names pointing at a
    resolved module-level constant -- exactly what every op.execute(...)
    call in this project's migrations does (verified against all of
    them, see this module's own docstring). Any other `{...}` expression
    (e.g. a `.join()` call) renders as _UNRESOLVED rather than crashing;
    a scan for the surrounding statement's role name just then can't
    match on that instead."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                if isinstance(value.value, ast.Name) and value.value.id in constants:
                    parts.append(constants[value.value.id])
                else:
                    parts.append(_UNRESOLVED)
        return "".join(parts)
    return None


def _is_op_call(node: ast.AST, attr: str) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
    )


def _literal_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _created_tables(fn: ast.FunctionDef) -> set[str]:
    return {
        name
        for node in ast.walk(fn)
        if _is_op_call(node, "create_table")
        and node.args
        and (name := _literal_str(node.args[0])) is not None
    }


def _dropped_tables(fn: ast.FunctionDef) -> set[str]:
    return {
        name
        for node in ast.walk(fn)
        if _is_op_call(node, "drop_table")
        and node.args
        and (name := _literal_str(node.args[0])) is not None
    }


def _added_columns(fn: ast.FunctionDef) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(fn):
        if not _is_op_call(node, "add_column") or len(node.args) < 2:
            continue
        table = _literal_str(node.args[0])
        column_call = node.args[1]
        if table is None or not isinstance(column_call, ast.Call) or not column_call.args:
            continue
        column = _literal_str(column_call.args[0])
        if column is not None:
            pairs.add((table, column))
    return pairs


def _dropped_columns(fn: ast.FunctionDef) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(fn):
        if not _is_op_call(node, "drop_column") or len(node.args) < 2:
            continue
        table = _literal_str(node.args[0])
        column = _literal_str(node.args[1])
        if table is not None and column is not None:
            pairs.add((table, column))
    return pairs


def _op_execute_texts(fn: ast.FunctionDef, constants: dict[str, str]) -> list[str]:
    texts = []
    for node in ast.walk(fn):
        if _is_op_call(node, "execute") and node.args:
            resolved = _resolve_string_expr(node.args[0], constants)
            if resolved is not None:
                texts.append(resolved)
    return texts


def _granted_roles(texts: list[str]) -> set[str]:
    return {match.group(1) for text in texts for match in _GRANT_TO_RE.finditer(text)}


def _revoked_or_dropped_roles(texts: list[str]) -> set[str]:
    roles = {match.group(1) for text in texts for match in _REVOKE_FROM_RE.finditer(text)}
    roles |= {match.group(1) for text in texts for match in _DROP_ROLE_RE.finditer(text)}
    return roles


def check_migration(path: Path) -> list[str]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    constants = _module_string_constants(tree)

    upgrade_fn = _find_function(tree, "upgrade")
    downgrade_fn = _find_function(tree, "downgrade")
    if upgrade_fn is None or downgrade_fn is None:
        return [f"{path.name}: missing upgrade() or downgrade() function"]

    errors: list[str] = []

    created = _created_tables(upgrade_fn)
    dropped = _dropped_tables(downgrade_fn)
    for table in sorted(created - dropped):
        errors.append(
            f"{path.name}: upgrade() creates table \"{table}\" but downgrade() never drops it"
        )

    added = _added_columns(upgrade_fn)
    removed = _dropped_columns(downgrade_fn)
    for table, column in sorted(added - removed):
        errors.append(
            f"{path.name}: upgrade() adds column \"{table}.{column}\" but downgrade() "
            "never drops it"
        )

    upgrade_texts = _op_execute_texts(upgrade_fn, constants)
    downgrade_texts = _op_execute_texts(downgrade_fn, constants)
    granted = _granted_roles(upgrade_texts)
    revoked_or_dropped = _revoked_or_dropped_roles(downgrade_texts)
    for role in sorted(granted - revoked_or_dropped):
        errors.append(
            f'{path.name}: upgrade() GRANTs to role "{role}" but downgrade() never '
            "REVOKEs or DROPs it"
        )

    return errors


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _default_migration_files() -> list[Path]:
    """Migrations changed vs. `main`, *plus* uncommitted ones.

    The working-tree half is not an extra: without it this returns an
    empty list on the normal case — a branch whose migration has been
    written but not yet committed — and the check prints "0 file(s)" and
    exits zero, which reads exactly like a pass. `scripts/check_coupled_files.py`
    already looks at the working tree in its no-argument mode for the
    same reason; this was the odd one out, and the gap was found by the
    Phase 26 audit finding this gate silently checking nothing on a
    branch that had two new migrations sitting in it.
    """
    paths = set(
        _git_lines("diff", "--name-only", "main...HEAD", "--", "api/migrations/versions/")
    )
    # Staged + unstaged + untracked, the same set `git status --porcelain`
    # reports, restricted to migration files.
    for line in _git_lines("status", "--porcelain=v1", "--", "api/migrations/versions/"):
        # "XY path", and "XY old -> new" for a rename: the new path is
        # the one that still exists to be checked.
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.add(path.strip('"'))

    return sorted(
        (ROOT / path for path in paths if (ROOT / path).exists()), key=lambda p: p.name
    )


def main(argv: list[str]) -> int:
    files = [Path(arg) for arg in argv] if argv else _default_migration_files()

    errors: list[str] = []
    for path in files:
        if path.suffix != ".py":
            continue
        errors.extend(check_migration(path))

    if errors:
        print("Migration symmetry violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"No migration symmetry violations across {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
