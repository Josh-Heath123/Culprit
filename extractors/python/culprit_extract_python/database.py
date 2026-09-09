"""Database schema and migration head.

Two claims, both INTENT and both about what the *code* expects — not
about any live database. `schema:` facts here say "the models declare a
table called orders with these columns"; whether a real database has
them is a CONFIGURED question for Phase 30. Keeping that straight is the
whole reason the planes exist.

SQLAlchemy metadata is read from mapped classes discovered in
`sys.modules` after the app has been imported, rather than from a
hardcoded `models.Base`. There is no convention for where a project
keeps its declarative base, and importing the app has already had the
side effect of importing whatever defines it.
"""

import sys
from pathlib import Path
from typing import Any

from culprit_model import build
from culprit_model.planes import ConfidenceRank, SourceKind
from culprit_model.protocol import Predicate

from culprit_extract_python.emit import FactBuilder

#: The `database` part of a `schema:` subject when the project does not
#: say which database its tables live in.
#:
#: A placeholder, and an honest one: the models declare a schema, they do
#: not declare which deployed database instance holds it. Phase 30's
#: environment capture is what supplies a real name; until then, every
#: schema subject from this extractor is scoped to the component that
#: declares it, which is at least unambiguous within one system model.
DEFAULT_DATABASE_SUFFIX = "-db"


def extract_schema(builder: FactBuilder) -> list[Any]:
    """Emits one fact per mapped table and one per column.

    Both, not just the table: a column-level subject is what makes
    "staging is missing orders.total_cents" expressible, and that is the
    single most common schema divergence there is.
    """
    tables = _mapped_tables()
    if not tables:
        return []

    database = f"{builder.component}{DEFAULT_DATABASE_SUFFIX}"
    facts: list[Any] = []
    for table in sorted(tables, key=lambda item: (item.schema or "public", item.name)):
        namespace = table.schema or "public"
        try:
            table_subject = build(
                "schema", database=database, namespace=namespace, table=table.name
            )
        except Exception:  # a table name with a separator in it
            continue

        columns = sorted(column.name for column in table.columns)
        facts.append(
            builder.fact(
                table_subject,
                Predicate.COLUMNS,
                columns,
                source_kind=SourceKind.INTROSPECTION,
                artefact=builder.app_target,
                locator=f"{namespace}.{table.name}",
                rank=ConfidenceRank.RUNTIME_INTROSPECTION,
            )
        )

        for column in sorted(table.columns, key=lambda item: item.name):
            try:
                column_subject = build(
                    "schema",
                    database=database,
                    namespace=namespace,
                    table=table.name,
                    column=column.name,
                )
            except Exception:
                continue
            facts.append(
                builder.fact(
                    column_subject,
                    Predicate.COLUMN_TYPE,
                    _column_type(column),
                    source_kind=SourceKind.INTROSPECTION,
                    artefact=builder.app_target,
                    locator=f"{namespace}.{table.name}.{column.name}",
                    rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                )
            )
            facts.append(
                builder.fact(
                    column_subject,
                    Predicate.NULLABLE,
                    bool(column.nullable),
                    source_kind=SourceKind.INTROSPECTION,
                    artefact=builder.app_target,
                    locator=f"{namespace}.{table.name}.{column.name}",
                    rank=ConfidenceRank.RUNTIME_INTROSPECTION,
                )
            )
    return facts


def _column_type(column: Any) -> str:
    """A column's type as a comparable string.

    The *generic* type name where SQLAlchemy can give one, because
    `VARCHAR(255)` and `String(255)` describe the same intent and must
    compare equal. Falling back to `str(column.type)` when it cannot is
    a slightly noisier answer, not a wrong one.
    """
    try:
        return type(column.type).__name__.upper()
    except Exception:
        return str(column.type).upper()


def _mapped_tables() -> list[Any]:
    """Every SQLAlchemy Table reachable from an imported declarative base.

    Deduplicated by identity: several modules commonly re-export the same
    `Base`, and each `MetaData` would otherwise contribute the same
    tables again.
    """
    seen: dict[int, Any] = {}
    for module in list(sys.modules.values()):
        if module is None:
            continue
        metadata = getattr(module, "metadata", None)
        candidates = [metadata]
        base = getattr(module, "Base", None)
        if base is not None:
            candidates.append(getattr(base, "metadata", None))
        for candidate in candidates:
            tables = getattr(candidate, "tables", None)
            if not isinstance(tables, dict):
                continue
            for table in tables.values():
                if hasattr(table, "columns") and hasattr(table, "name"):
                    seen[id(table)] = table
    return list(seen.values())


def extract_migration_head(root: Path, builder: FactBuilder) -> list[Any]:
    """The Alembic head, asked of Alembic rather than guessed.

    The Go side computes this from the versions directory when nothing is
    installed (`cli/internal/extract/config_keys.go`). This is the better
    answer where it is available, because `ScriptDirectory` understands
    branch labels and `depends_on`, which a line scan does not — and
    because when the two disagree, the disagreement is itself worth
    seeing.
    """
    from alembic.config import Config  # optional, guarded by the caller
    from alembic.script import ScriptDirectory
    ini = _find_alembic_ini(root)
    if ini is None:
        return []
    script = ScriptDirectory.from_config(Config(str(ini)))
    heads = sorted(script.get_heads())
    subject = build("component", name=builder.component)
    return [
        builder.fact(
            subject,
            Predicate.MIGRATION_HEAD,
            heads,
            source_kind=SourceKind.INTROSPECTION,
            artefact=str(ini.relative_to(root)) if ini.is_relative_to(root) else str(ini),
            locator=None,
            rank=ConfidenceRank.RUNTIME_INTROSPECTION,
        )
    ]


def _find_alembic_ini(root: Path) -> Path | None:
    direct = root / "alembic.ini"
    if direct.is_file():
        return direct
    # One level down covers the very common `api/alembic.ini` layout
    # without turning this into a whole-tree walk.
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        candidate = child / "alembic.ini"
        if child.is_dir() and candidate.is_file():
            return candidate
    return None
