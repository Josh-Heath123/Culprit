"""Unit tests for scripts/check_migration_symmetry.py (Phase 22,
docs/AI_NATIVE_PLAN.md). scripts/ has no test precedent before this
phase (see that module's own docstring) -- this sets it.

Each test writes a synthetic migration file to tmp_path and calls
check_migration() directly rather than shelling out to the script's own
main(), since main() is just argv handling + printing around this one
function. The real-migration regression test at the bottom is the
actual proof for this phase's own acceptance criterion ("zero false
positives on every real, already-shipped migration") -- already run
manually during this phase's own verification, locked in here so it
stays true.
"""

from pathlib import Path

import check_migration_symmetry as sym

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "api" / "migrations" / "versions"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_symmetric_migration_passes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "aaa_symmetric.py",
        '''
from alembic import op
import sqlalchemy as sa

ROLE = "some-role"


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer(), primary_key=True))
    op.add_column("widgets", sa.Column("name", sa.String(), nullable=True))
    op.execute(f'GRANT SELECT ON widgets TO "{ROLE}"')


def downgrade() -> None:
    op.execute(f'REVOKE SELECT ON widgets FROM "{ROLE}"')
    op.drop_column("widgets", "name")
    op.drop_table("widgets")
''',
    )
    assert sym.check_migration(path) == []


def test_symmetric_migration_using_drop_role_instead_of_revoke_passes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "aab_drop_role.py",
        '''
from alembic import op

ROLE = "some-role"


def upgrade() -> None:
    op.execute(f'CREATE ROLE "{ROLE}" LOGIN')
    op.execute(f'GRANT SELECT ON widgets TO "{ROLE}"')


def downgrade() -> None:
    op.execute(f'DROP ROLE IF EXISTS "{ROLE}"')
''',
    )
    assert sym.check_migration(path) == []


def test_missing_drop_table_fails_naming_the_table(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bbb_missing_drop.py",
        '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    pass
''',
    )
    errors = sym.check_migration(path)
    assert len(errors) == 1
    assert "widgets" in errors[0]
    assert "downgrade" in errors[0]


def test_missing_drop_column_fails_naming_the_column(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ccc_missing_drop_column.py",
        '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("widgets", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    pass
''',
    )
    errors = sym.check_migration(path)
    assert len(errors) == 1
    assert "widgets.name" in errors[0]


def test_missing_revoke_fails_naming_the_role(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ddd_missing_revoke.py",
        '''
from alembic import op

ROLE = "some-role"


def upgrade() -> None:
    op.execute(f'GRANT SELECT ON widgets TO "{ROLE}"')


def downgrade() -> None:
    pass
''',
    )
    errors = sym.check_migration(path)
    assert len(errors) == 1
    assert "some-role" in errors[0]


def test_migration_with_no_grants_at_all_passes_trivially(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "eee_no_grants.py",
        '''
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table("widgets", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    op.drop_table("widgets")
''',
    )
    assert sym.check_migration(path) == []


def test_role_name_via_module_level_fstring_constant_resolves(tmp_path: Path) -> None:
    """Trap 4: several real migrations build role names from a
    module-level string constant inside an f-string
    (`f'GRANT ... TO "{ROLE_NAME}"'`), not a literal. The checker must
    resolve that, not just literal strings."""
    path = _write(
        tmp_path,
        "fff_fstring_role.py",
        '''
from alembic import op

MY_ROLE_CONSTANT = "my-role-name"


def upgrade() -> None:
    op.execute(f'GRANT SELECT ON widgets TO "{MY_ROLE_CONSTANT}"')


def downgrade() -> None:
    pass
''',
    )
    errors = sym.check_migration(path)
    assert len(errors) == 1
    assert "my-role-name" in errors[0]


def test_unresolvable_fstring_expression_does_not_crash(tmp_path: Path) -> None:
    """cc323b6c7779's own pattern: an f-string `{...}` part that isn't a
    bare Name (here, a `.join()` call) must not crash the checker -- it
    just can't be used to resolve a role name."""
    path = _write(
        tmp_path,
        "ggg_unresolvable.py",
        '''
from alembic import op

TABLES = ("a", "b")


def upgrade() -> None:
    op.execute(f'GRANT SELECT ON {", ".join(TABLES)} TO "some-role"')


def downgrade() -> None:
    op.execute('REVOKE SELECT ON a, b FROM "some-role"')
''',
    )
    assert sym.check_migration(path) == []


def test_missing_upgrade_or_downgrade_reports_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "hhh_no_functions.py", "revision = 'x'\n")
    errors = sym.check_migration(path)
    assert len(errors) == 1
    assert "upgrade" in errors[0] or "downgrade" in errors[0]


def test_every_real_shipped_migration_has_zero_false_positives() -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.py"))
    assert len(migration_files) > 0, "expected real migrations under api/migrations/versions/"
    for path in migration_files:
        errors = sym.check_migration(path)
        assert errors == [], f"{path.name}: unexpected false positive(s): {errors}"
