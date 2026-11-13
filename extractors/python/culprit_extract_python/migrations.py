"""The schema the migration chain builds, read from the migration files.

# Why this exists

Phase 29 acceptance criterion 2 is "detects an ORM model whose column is
absent from the migration head". Nothing in the repository could answer
it: `database.py` reads the schema the *models* declare, and the only
migration fact anywhere was the head revision id — a version string,
which tells you nothing about what columns exist.

So this module replays the chain and reports the tables and columns it
ends up creating. Compared against the ORM's own `columns` fact for the
same table subject, a column added to a model and never migrated is a
plain value disagreement, found by the generic comparator with no
special case (D7).

# How it reads them, and what that costs

Statically, with `ast` — never by importing or executing a migration.
Running one would need a database, which is a Phase 30 capability this
phase does not have and should not want; and a migration is arbitrary
code that may do anything at all.

The price is real and is written down in `docs/LIMITS.md`: this
understands the literal Alembic operations
(`create_table`, `add_column`, `drop_column`, `drop_table`,
`alter_column ... new_column_name`, `rename_table`) and nothing else. A
migration that builds its column list in a loop, or runs raw
`op.execute("ALTER TABLE ...")`, is invisible to it.

That is why the answer is emitted at **rank 80** — a committed spec —
and never at rank 90. It sits below the ORM's runtime introspection, so
when the two disagree the report names the ORM as the reference and the
migration chain as the side that differs, which is the right way round:
the models are what the code will actually try to use.

# The honesty rule, applied to itself

If the chain cannot be ordered — a missing `down_revision`, a cycle, two
heads — this emits **nothing** and says why. A partially-replayed chain
would produce a confident list of columns that is simply wrong, and
every difference against it would be a false positive. Criterion 6 says
zero findings on a correct fixture, and a guess here is the cheapest
possible way to break it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from culprit_model import build
from culprit_model.planes import ConfidenceRank, SourceKind
from culprit_model.protocol import Predicate

# The database part of a subject is FactBuilder.schema_database, shared
# with database.py: the two must produce the same subject for the same
# table or nothing compares.
from culprit_extract_python.emit import FactBuilder


class ChainError(Exception):
    """The revision chain could not be ordered, so nothing is emitted."""


def extract_migration_schema(root: Path, builder: FactBuilder) -> list[Any]:
    """One `columns` fact per table the migration chain leaves behind."""
    versions = _find_versions_dir(root)
    if versions is None:
        return []

    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    revisions = [revision for revision in revisions if revision is not None]
    if not revisions:
        return []

    ordered = _order(revisions)
    tables = _replay(ordered)
    if not tables:
        return []
    leading = _leading_columns(_replay_indexes(ordered))

    database = builder.schema_database
    # `as_posix()`, not `str()`: an artefact path is compared and reported
    # across machines, and `migrations\versions` from a Windows run
    # naming the same file as `migrations/versions` from CI is exactly the
    # drift Phase 28's `relative()` helper exists to prevent on the Go
    # side. Caught by reading the demo repository's own output.
    artefact = (
        versions.relative_to(root).as_posix()
        if versions.is_relative_to(root)
        else versions.as_posix()
    )
    facts: list[Any] = []
    for name in sorted(tables):
        namespace, table = name
        try:
            subject = build("schema", database=database, namespace=namespace, table=table)
        except Exception:  # a table name with a separator in it
            continue
        facts.append(
            builder.fact(
                subject,
                Predicate.COLUMNS,
                sorted(tables[name]),
                source_kind=SourceKind.SPEC,
                artefact=artefact,
                locator=f"{namespace}.{table}",
                rank=ConfidenceRank.COMMITTED_SPEC,
            )
        )
        # Phase 37 part 1: for every column, whether the migrations leave an
        # index led by it. True and false both, so the comparator sees a
        # plain disagreement when the live database differs either way.
        for column in sorted(tables[name]):
            try:
                column_subject = build(
                    "schema", database=database, namespace=namespace, table=table, column=column
                )
            except Exception:
                continue
            facts.append(
                builder.fact(
                    column_subject,
                    Predicate.LEADS_INDEX,
                    column in leading.get(name, set()),
                    source_kind=SourceKind.SPEC,
                    artefact=artefact,
                    locator=f"{namespace}.{table}.{column}",
                    rank=ConfidenceRank.COMMITTED_SPEC,
                )
            )
    return facts


# --- reading one file -------------------------------------------------


class _Revision:
    __slots__ = ("down_revision", "path", "revision", "tree")

    def __init__(self, path: Path, revision: str, down_revision: Any, tree: ast.Module):
        self.path = path
        self.revision = revision
        self.down_revision = down_revision
        self.tree = tree


def _read_revision(path: Path) -> _Revision | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    revision: str | None = None
    down: Any = None
    # Both `revision = "x"` and Alembic's own generated
    # `revision: str = "x"` — an annotated assignment is a different AST
    # node, and reading only the bare one found zero revisions in this
    # repository's own migrations, which is how the omission was caught.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if target.id == "revision":
                revision = _literal(value)
            elif target.id == "down_revision":
                down = _literal(value)
    if not isinstance(revision, str):
        return None
    return _Revision(path, revision, down, tree)


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


# --- ordering the chain -----------------------------------------------


def _order(revisions: list[_Revision]) -> list[_Revision]:
    """Topologically order a linear chain, or raise.

    Branching chains raise rather than pick an order. Alembic supports
    branches and this does not — and an arbitrary linearisation of a
    branched history is a schema that never existed, which would be
    worse than declining to answer.
    """
    by_revision = {revision.revision: revision for revision in revisions}
    if len(by_revision) != len(revisions):
        raise ChainError("two migrations declare the same revision id")

    children: dict[Any, list[_Revision]] = {}
    for revision in revisions:
        down = revision.down_revision
        if isinstance(down, (list, tuple)):
            raise ChainError(
                f"{revision.path.name} is a merge revision; "
                "branched histories are not replayed"
            )
        children.setdefault(down, []).append(revision)

    roots = children.get(None, [])
    if len(roots) != 1:
        raise ChainError(
            f"expected exactly one migration with down_revision = None, found {len(roots)}"
        )

    ordered: list[_Revision] = []
    current: Any = None
    seen: set[str] = set()
    while True:
        next_up = children.get(current, [])
        if not next_up:
            break
        if len(next_up) > 1:
            raise ChainError(
                f"revision {current} has {len(next_up)} children; "
                "branched histories are not replayed"
            )
        revision = next_up[0]
        if revision.revision in seen:
            raise ChainError("the revision chain contains a cycle")
        seen.add(revision.revision)
        ordered.append(revision)
        current = revision.revision

    if len(ordered) != len(revisions):
        missing = sorted(set(by_revision) - seen)
        raise ChainError(
            f"{len(missing)} migration(s) are not reachable from the root: "
            + ", ".join(missing[:3])
        )
    return ordered


# --- replaying the operations -----------------------------------------

Tables = dict[tuple[str, str], set[str]]


def _replay(ordered: list[_Revision]) -> Tables:
    tables: Tables = {}
    for revision in ordered:
        upgrade = _function(revision.tree, "upgrade")
        if upgrade is None:
            continue
        for call in _op_calls(upgrade):
            _apply(tables, call)
    return tables


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _op_calls(function: ast.FunctionDef) -> list[ast.Call]:
    """Every `op.<something>(...)` call in the function body.

    `ast.walk`, so a call inside an `if` or a `with` is still seen. A
    conditional migration is rare and replaying both branches is the
    wrong answer, but so is ignoring the body entirely — this over-reads
    rather than under-reads, and `docs/LIMITS.md` says so.
    """
    calls: list[ast.Call] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "op"
        ):
            calls.append(node)
    return calls


def _apply(tables: Tables, call: ast.Call) -> None:
    operation = call.func.attr  # type: ignore[union-attr]
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    schema = _literal(keywords["schema"]) if "schema" in keywords else "public"
    if not isinstance(schema, str):
        schema = "public"

    if operation == "create_table":
        if not call.args:
            return
        name = _literal(call.args[0])
        if not isinstance(name, str):
            return
        tables[(schema, name)] = {
            column
            for column in (_column_name(argument) for argument in call.args[1:])
            if column is not None
        }

    elif operation == "add_column":
        if len(call.args) < 2:
            return
        name = _literal(call.args[0])
        column = _column_name(call.args[1])
        if isinstance(name, str) and column is not None:
            tables.setdefault((schema, name), set()).add(column)

    elif operation == "drop_column":
        if len(call.args) < 2:
            return
        name, column = _literal(call.args[0]), _literal(call.args[1])
        if isinstance(name, str) and isinstance(column, str):
            tables.get((schema, name), set()).discard(column)

    elif operation == "drop_table":
        if not call.args:
            return
        name = _literal(call.args[0])
        if isinstance(name, str):
            tables.pop((schema, name), None)

    elif operation == "rename_table":
        if len(call.args) < 2:
            return
        old, new = _literal(call.args[0]), _literal(call.args[1])
        if isinstance(old, str) and isinstance(new, str) and (schema, old) in tables:
            tables[(schema, new)] = tables.pop((schema, old))

    elif operation == "alter_column":
        # Only the rename matters here; a type change does not alter the
        # column *set*, which is what this fact is about.
        new_name = _literal(keywords["new_column_name"]) if "new_column_name" in keywords else None
        if len(call.args) < 2 or not isinstance(new_name, str):
            return
        name, column = _literal(call.args[0]), _literal(call.args[1])
        if isinstance(name, str) and isinstance(column, str):
            columns = tables.get((schema, name))
            if columns is not None and column in columns:
                columns.discard(column)
                columns.add(new_name)


# --- indexes (Phase 37 part 1) -----------------------------------------

#: Per table, every index the chain leaves behind: its name (or a stand-in
#: for one created unnamed with the table) and its key columns, in order.
Indexes = dict[tuple[str, str], dict[str, list[str]]]


def _replay_indexes(ordered: list[_Revision]) -> Indexes:
    """The indexes the chain leaves behind, for whether a column *leads*
    one: an index on (a, b) serves a filter on a, not on b, and that is what
    a missing-index finding needs (PERFORMANCE_PLAN.md P5).

    The same static reading as the columns, with the same limit: the
    literal operations only. Read: a column's `primary_key=True`,
    `unique=True` or `index=True`; `sa.PrimaryKeyConstraint` and
    `sa.UniqueConstraint` in `create_table`; `create_index` and
    `drop_index`; `create_unique_constraint`, `create_primary_key` and a
    named `drop_constraint`. A partial index (`postgresql_where=`) or one on
    an expression is not counted, as the live side does not count it.
    """
    indexes: Indexes = {}
    for revision in ordered:
        upgrade = _function(revision.tree, "upgrade")
        if upgrade is None:
            continue
        for call in _op_calls(upgrade):
            _apply_index(indexes, call)
    return indexes


def _leading_columns(indexes: Indexes) -> dict[tuple[str, str], set[str]]:
    return {
        table: {columns[0] for columns in named.values() if columns}
        for table, named in indexes.items()
    }


def _string_list(node: ast.AST) -> list[str] | None:
    """A literal list or tuple of column names, or None when any is not a
    plain string (an expression index, a computed list)."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    names = [_literal(element) for element in node.elts]
    if not names or not all(isinstance(name, str) for name in names):
        return None
    return [str(name) for name in names]


def _index_name(node: ast.AST) -> str | None:
    """A literal name, or `op.f("name")`."""
    if isinstance(node, ast.Call) and node.args and getattr(node.func, "attr", None) == "f":
        node = node.args[0]
    literal = _literal(node)
    return literal if isinstance(literal, str) else None


def _apply_index(indexes: Indexes, call: ast.Call) -> None:
    operation = call.func.attr  # type: ignore[union-attr]
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    schema = _literal(keywords["schema"]) if "schema" in keywords else "public"
    if not isinstance(schema, str):
        schema = "public"

    def table_of(position: int, keyword: str) -> tuple[str, str] | None:
        node = call.args[position] if len(call.args) > position else keywords.get(keyword)
        name = _literal(node) if node is not None else None
        return (schema, name) if isinstance(name, str) else None

    if operation == "create_table":
        table = table_of(0, "table_name")
        if table is None:
            return
        named = indexes.setdefault(table, {})
        primary: list[str] = []
        for position, argument in enumerate(call.args[1:]):
            if not isinstance(argument, ast.Call):
                continue
            function = argument.func
            kind = (
                function.attr
                if isinstance(function, ast.Attribute)
                else getattr(function, "id", None)
            )
            flags = {keyword.arg: _literal(keyword.value) for keyword in argument.keywords}
            if kind == "Column":
                column = _column_name(argument)
                if column is None:
                    continue
                if flags.get("primary_key") is True:
                    primary.append(column)
                if flags.get("unique") is True:
                    named[f"<unique {column}>"] = [column]
                if flags.get("index") is True:
                    named[f"<index {column}>"] = [column]
            elif kind in ("PrimaryKeyConstraint", "UniqueConstraint"):
                columns = [_literal(node) for node in argument.args]
                if not columns or not all(isinstance(name, str) for name in columns):
                    continue
                name = flags.get("name")
                key = name if isinstance(name, str) else f"<{kind} {position}>"
                if kind == "PrimaryKeyConstraint":
                    primary = [str(column) for column in columns]
                    key = name if isinstance(name, str) else "<primary key>"
                named[key] = [str(column) for column in columns]
        if primary and "<primary key>" not in named and not any(
            columns == primary for columns in named.values()
        ):
            named["<primary key>"] = primary

    elif operation in ("create_index", "create_unique_constraint", "create_primary_key"):
        if "postgresql_where" in keywords or len(call.args) < 2:
            return
        name = _index_name(call.args[0])
        table = table_of(1, "table_name")
        columns = _string_list(call.args[2]) if len(call.args) > 2 else (
            _string_list(keywords["columns"]) if "columns" in keywords else None
        )
        if name is None or table is None or columns is None:
            return
        indexes.setdefault(table, {})[name] = columns

    elif operation in ("drop_index", "drop_constraint"):
        if not call.args:
            return
        name = _index_name(call.args[0])
        if name is None:
            return
        named_table = table_of(1, "table_name")
        for table, named in indexes.items():
            if named_table is None or table == named_table:
                named.pop(name, None)

    elif operation == "drop_table":
        table = table_of(0, "table_name")
        if table is not None:
            indexes.pop(table, None)

    elif operation == "drop_column":
        if len(call.args) < 2:
            return
        table, column = table_of(0, "table_name"), _literal(call.args[1])
        if table is not None and isinstance(column, str):
            named = indexes.get(table, {})
            for key in [key for key, columns in named.items() if column in columns]:
                del named[key]

    elif operation == "rename_table":
        old, new = table_of(0, "old_table_name"), table_of(1, "new_table_name")
        if old is not None and new is not None and old in indexes:
            indexes[new] = indexes.pop(old)

    elif operation == "alter_column":
        new_name = _literal(keywords["new_column_name"]) if "new_column_name" in keywords else None
        table = table_of(0, "table_name")
        column = _literal(call.args[1]) if len(call.args) > 1 else None
        if table is None or not isinstance(column, str) or not isinstance(new_name, str):
            return
        for columns in indexes.get(table, {}).values():
            columns[:] = [new_name if name == column else name for name in columns]


def _column_name(node: ast.AST) -> str | None:
    """The name out of a `sa.Column("total_cents", ...)` argument."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "Column" or not node.args:
        return None
    literal = _literal(node.args[0])
    return literal if isinstance(literal, str) else None


def _find_versions_dir(root: Path) -> Path | None:
    """The Alembic `versions/` directory, without a whole-tree walk.

    Bounded to three levels because the layouts that occur in practice
    are `migrations/versions`, `alembic/versions` and
    `api/migrations/versions`, and an unbounded walk of a monorepo is the
    kind of cost that turns a 30-second budget into a 3-minute one.
    """
    if not root.is_dir():
        return None
    candidates = [
        root.glob("*/versions"),
        root.glob("*/*/versions"),
        root.glob("*/*/*/versions"),
    ]
    for generation in candidates:
        for path in sorted(generation):
            if path.is_dir() and any(path.glob("*.py")):
                return path
    return None
