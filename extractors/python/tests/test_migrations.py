"""The migration-chain reader.

The tests worth reading twice are the refusals. This module's whole
safety argument is that it declines rather than guessing when the chain
does not form a single line — a partially replayed chain produces a
confident column list that is simply wrong, and every difference against
it becomes a false positive in somebody's CI.
"""

from pathlib import Path

import pytest
from culprit_extract_python.migrations import (
    ChainError,
    _order,
    _read_revision,
    _replay,
    extract_migration_schema,
)


def write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def revision_file(
    revision: str, down: str | None, upgrade: str, *, annotated: bool = True
) -> str:
    """One migration, in Alembic's own generated shape by default."""
    down_literal = "None" if down is None else f'"{down}"'
    if annotated:
        header = (
            f'revision: str = "{revision}"\n'
            f"down_revision: str | None = {down_literal}\n"
        )
    else:
        header = f'revision = "{revision}"\ndown_revision = {down_literal}\n'
    return (
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        f"{header}\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade}\n\n\n"
        "def downgrade() -> None:\n"
        "    pass\n"
    )


CREATE_ORDERS = """    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )"""


def chain(tmp_path: Path, *files: str) -> Path:
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    for index, body in enumerate(files):
        write(versions, f"{index:04d}_revision.py", body)
    return versions


# --- reading one file ---------------------------------------------------


@pytest.mark.parametrize("annotated", [True, False])
def test_both_assignment_styles_are_read(tmp_path: Path, annotated: bool) -> None:
    """`revision = "x"` and Alembic's `revision: str = "x"`.

    An annotated assignment is a different AST node, and reading only the
    bare one found zero revisions in Culprit's own 23-migration chain —
    silently, because zero revisions looks exactly like no migrations.
    """
    path = write(
        tmp_path,
        "0001.py",
        revision_file("abc123", None, CREATE_ORDERS, annotated=annotated),
    )
    revision = _read_revision(path)
    assert revision is not None
    assert revision.revision == "abc123"
    assert revision.down_revision is None


def test_a_file_that_is_not_a_migration_is_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "__init__.py", "# nothing here\n")
    assert _read_revision(path) is None


def test_a_file_that_does_not_parse_is_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "broken.py", "def upgrade(:\n")
    assert _read_revision(path) is None


# --- replaying operations -----------------------------------------------


def test_the_chain_is_replayed_in_order(tmp_path: Path) -> None:
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file(
            "0002",
            "0001",
            '    op.add_column("orders", sa.Column("total_cents", sa.Integer()))',
        ),
        revision_file("0003", "0002", '    op.drop_column("orders", "created_at")'),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    tables = _replay(_order([r for r in revisions if r]))
    assert tables == {("public", "orders"): {"id", "total_cents"}}


def test_a_renamed_column_follows_the_rename(tmp_path: Path) -> None:
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file(
            "0002",
            "0001",
            '    op.alter_column("orders", "created_at", new_column_name="placed_at")',
        ),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    tables = _replay(_order([r for r in revisions if r]))
    assert tables == {("public", "orders"): {"id", "placed_at"}}


def test_a_dropped_table_disappears(tmp_path: Path) -> None:
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file("0002", "0001", '    op.drop_table("orders")'),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    assert _replay(_order([r for r in revisions if r])) == {}


def test_a_non_public_schema_is_kept_separate(tmp_path: Path) -> None:
    versions = chain(
        tmp_path,
        revision_file(
            "0001",
            None,
            '    op.create_table(\n'
            '        "orders",\n'
            '        sa.Column("id", sa.Integer()),\n'
            '        schema="billing",\n'
            "    )",
        ),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    assert _replay(_order([r for r in revisions if r])) == {
        ("billing", "orders"): {"id"}
    }


# --- the refusals -------------------------------------------------------


def test_a_branched_chain_is_refused(tmp_path: Path) -> None:
    """Two migrations with the same parent.

    Alembic supports branches; this does not. An arbitrary linearisation
    of a branched history describes a schema that never existed.
    """
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file("0002", "0001", '    op.add_column("orders", sa.Column("a", sa.Integer()))'),
        revision_file("0003", "0001", '    op.add_column("orders", sa.Column("b", sa.Integer()))'),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    with pytest.raises(ChainError, match="branched"):
        _order([r for r in revisions if r])


def test_two_roots_are_refused(tmp_path: Path) -> None:
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file(
            "0002", None, '    op.create_table("invoices", sa.Column("id", sa.Integer()))'
        ),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    with pytest.raises(ChainError, match="down_revision = None"):
        _order([r for r in revisions if r])


def test_an_unreachable_migration_is_refused(tmp_path: Path) -> None:
    """A file whose parent is not in the directory.

    Replaying the reachable part would silently omit whatever the orphan
    did, and report the result as the schema.
    """
    versions = chain(
        tmp_path,
        revision_file("0001", None, CREATE_ORDERS),
        revision_file("0009", "0008", '    op.add_column("orders", sa.Column("a", sa.Integer()))'),
    )
    revisions = [_read_revision(path) for path in sorted(versions.glob("*.py"))]
    with pytest.raises(ChainError):
        _order([r for r in revisions if r])


def test_a_merge_revision_is_refused(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "merge.py",
        'revision: str = "0003"\n'
        'down_revision: tuple[str, str] = ("0001", "0002")\n\n'
        "def upgrade() -> None:\n    pass\n",
    )
    revision = _read_revision(path)
    assert revision is not None
    with pytest.raises(ChainError, match="merge revision"):
        _order([revision])


def test_no_versions_directory_is_not_an_error(tmp_path: Path) -> None:
    """An empty answer, not an exception.

    A project with no migrations is a normal project, and the extractor's
    honesty rule is that it says nothing rather than failing the run.
    """

    class Builder:
        component = "orders-api"

    assert extract_migration_schema(tmp_path, Builder()) == []  # type: ignore[arg-type]


# --- indexes (Phase 37 part 1) -------------------------------------------


def _leads_index(tmp_path: Path, *bodies: str) -> dict[str, bool]:
    """Every leads_index fact the whole reader emits, by column."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from culprit_extract_python.emit import FactBuilder

    chain(
        tmp_path,
        *(
            revision_file(f"{index:04d}", f"{index - 1:04d}" if index else None, body)
            for index, body in enumerate(bodies)
        ),
    )
    builder = FactBuilder(
        component="shop",
        capture_id=uuid4(),
        captured_at=datetime(2026, 11, 12, tzinfo=UTC),
        extractor="test",
    )
    return {
        fact.subject.rsplit(".", 1)[1]: fact.value
        for fact in extract_migration_schema(tmp_path, builder)
        if fact.predicate == "leads_index"
    }


ITEMS = """    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
    )"""


def test_a_primary_key_and_a_created_index_lead_an_index(tmp_path: Path) -> None:
    leads = _leads_index(
        tmp_path,
        ITEMS,
        '    op.create_index(op.f("ix_items_sku"), "items", ["sku"], unique=False)',
    )
    assert leads == {"id": True, "sku": True, "category": False, "price": False}


def test_a_dropped_index_no_longer_leads(tmp_path: Path) -> None:
    leads = _leads_index(
        tmp_path,
        ITEMS,
        '    op.create_index("ix_items_sku", "items", ["sku"])',
        '    op.drop_index("ix_items_sku", table_name="items")',
    )
    assert leads["sku"] is False


def test_only_the_first_column_of_a_composite_index_leads(tmp_path: Path) -> None:
    leads = _leads_index(
        tmp_path, ITEMS, '    op.create_index("ix_c_p", "items", ["category", "price"])'
    )
    assert leads["category"] is True and leads["price"] is False


def test_a_partial_index_and_column_flags(tmp_path: Path) -> None:
    """A partial index serves only matching filters, and the live side does
    not count one either; `index=True` and `unique=True` on a column do."""
    leads = _leads_index(
        tmp_path,
        """    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(), unique=True),
        sa.Column("category", sa.String(), index=True),
        sa.Column("price", sa.Integer()),
        sa.PrimaryKeyConstraint("id"),
    )""",
        '    op.create_index("ix_price", "items", ["price"],'
        ' postgresql_where=sa.text("price > 0"))',
    )
    assert leads == {"id": True, "sku": True, "category": True, "price": False}


def test_a_dropped_column_takes_its_index_and_a_rename_follows(tmp_path: Path) -> None:
    leads = _leads_index(
        tmp_path,
        ITEMS,
        '    op.create_index("ix_c", "items", ["category"])',
        '    op.create_index("ix_p", "items", ["price"])',
        '    op.drop_column("items", "price")',
        '    op.alter_column("items", "category", new_column_name="kind")',
    )
    assert leads == {"id": True, "sku": False, "kind": True}


def test_the_demo_migrations_declare_their_indexes() -> None:
    """inventory-service's own migrations (Phase 37 part 1, P8), read as
    the extractor reads them: `products` is led by its primary key and the
    unique index on sku; `category`, which the list route filters on, is
    not — Phase 37 part 3's missing-index fault. cli/cmd/culprit's
    TestTheDemoDatabase holds the live side to the same two columns."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from culprit_extract_python.emit import FactBuilder

    root = Path(__file__).resolve().parents[3] / "demo-services" / "inventory_service"
    builder = FactBuilder(
        component="inventory-service",
        capture_id=uuid4(),
        captured_at=datetime(2026, 11, 12, tzinfo=UTC),
        extractor="test",
    )
    leads = {
        fact.subject: fact.value
        for fact in extract_migration_schema(root, builder)
        if fact.predicate == "leads_index"
    }
    from culprit_model import build

    declared = {"id": True, "sku": True, "category": False, "name": False, "price_cents": False}
    assert leads == {
        build(
            "schema",
            database="inventory-service-db",
            namespace="public",
            table="products",
            column=column,
        ): value
        for column, value in declared.items()
    }
