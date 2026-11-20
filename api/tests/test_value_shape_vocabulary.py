# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""The value-shape vocabulary in the database equals the one in the model.

`culprit_model.shape` defines four closed vocabularies — `ValueType`,
`LengthClass`, `ValueFormat`, `ValueScheme` — and the migration that builds
the `*_value_shape_is_closed` CHECK constraints writes them out again as
literals, because a migration must not import mutable application code
(.claude/rules/database.md). Two copies of one vocabulary agree only if
something compares them.

Until Phase 43's close-out (Q43) that something was a file pair in
scripts/coupled_files.yaml: change shape.py, change the migration in the
same diff. It checked that a file moved, not that the vocabularies agree,
and the first change to shape.py that touched no vocabulary (Q42's
classifier fix) could have passed it only by editing an applied migration.
This test compares the content instead, in both directions, with no
database: it fails exactly when they disagree, whichever file moved.

The migration is found structurally, never by revision id: the Alembic
chain is read by AST (never imported) and walked from its one head to its
base, and the vocabulary's migration is the latest on it whose source names
a `*_value_shape_is_closed` constraint. A later migration that rebuilds the
constraint is followed without editing this file. Anything it cannot find
or read fails it; it never skips.

`test_value_shape_constraint.py` holds the other half against a real
Postgres: every shape the model can produce, the database accepts.
"""

import ast
import re
from enum import StrEnum
from pathlib import Path

import pytest
from culprit_model.shape import LengthClass, ValueFormat, ValueScheme, ValueType

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

#: A constraint name, as a string literal in a migration's source.
CONSTRAINT = re.compile(r"^[a-z0-9_]+_value_shape_is_closed$")

#: Each module-level tuple, and the enum it must equal.
VOCABULARIES: dict[str, type[StrEnum]] = {
    "_VALUE_TYPES": ValueType,
    "_LENGTH_CLASSES": LengthClass,
    "_FORMATS": ValueFormat,
    "_SCHEMES": ValueScheme,
}


def _assigned(tree: ast.Module, name: str) -> ast.expr | None:
    """The value a module-level `name = ...` or `name: T = ...` assigns."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return node.value
    return None


def _chain(versions: Path) -> list[tuple[str, ast.Module]]:
    """The migrations from head to base, each with its parsed source."""
    files = sorted(versions.glob("*.py"))
    assert files, f"no migrations found in {versions}"
    by_revision: dict[str, tuple[str | None, str, ast.Module]] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _assigned(tree, "revision")
        down = _assigned(tree, "down_revision")
        assert isinstance(revision, ast.Constant) and isinstance(revision.value, str), (
            f"{path.name}: no string `revision` could be read"
        )
        assert isinstance(down, ast.Constant) and (
            down.value is None or isinstance(down.value, str)
        ), f"{path.name}: `down_revision` is not a single revision or None"
        assert revision.value not in by_revision, f"revision {revision.value} appears twice"
        by_revision[revision.value] = (down.value, path.name, tree)

    parents = {down for down, _, _ in by_revision.values() if down is not None}
    heads = sorted(set(by_revision) - parents)
    assert len(heads) == 1, f"the migration chain has {len(heads)} heads: {heads}"
    for down, name, _ in by_revision.values():
        assert down is None or down in by_revision, f"{name}: down_revision {down} is missing"

    chain: list[tuple[str, ast.Module]] = []
    current: str | None = heads[0]
    while current is not None:
        assert len(chain) <= len(by_revision), "the migration chain has a cycle"
        down, name, tree = by_revision[current]
        chain.append((name, tree))
        current = down
    assert len(chain) == len(by_revision), (
        f"{len(by_revision) - len(chain)} migration(s) are not on the chain from the head"
    )
    return chain


def _names_the_constraint(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and CONSTRAINT.match(node.value) is not None
        for node in ast.walk(tree)
    )


def vocabulary_migration(versions: Path = VERSIONS) -> tuple[str, ast.Module]:
    """The latest migration on the chain that names the constraint."""
    for name, tree in _chain(versions):
        if _names_the_constraint(tree):
            return name, tree
    raise AssertionError(f"no migration in {versions} names a *_value_shape_is_closed constraint")


def _literals(name: str, tree: ast.Module, variable: str) -> list[str]:
    value = _assigned(tree, variable)
    assert isinstance(value, ast.Tuple), f"{name}: no module-level tuple `{variable}`"
    items: list[str] = []
    for element in value.elts:
        assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
            f"{name}: `{variable}` holds something that is not a string literal"
        )
        items.append(element.value)
    return items


@pytest.mark.parametrize("variable", sorted(VOCABULARIES))
def test_the_migrations_vocabulary_equals_the_models(variable: str) -> None:
    name, tree = vocabulary_migration()
    literals = _literals(name, tree, variable)
    duplicates = sorted({item for item in literals if literals.count(item) > 1})
    assert not duplicates, f"{name}: `{variable}` repeats {duplicates}"

    model = {member.value for member in VOCABULARIES[variable]}
    database = set(literals)
    assert database == model, (
        f"{name}: `{variable}` and {VOCABULARIES[variable].__name__} disagree - "
        f"only in the migration: {sorted(database - model)}; "
        f"only in the model: {sorted(model - database)}"
    )
