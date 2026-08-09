"""Adds scripts/ (this directory's parent) to sys.path so
test_check_*.py can `import check_coupled_files` / `import
check_migration_symmetry` directly -- both are standalone modules (no
__init__.py, not part of a package), matching how they're actually
invoked in production (`uv run --project api python scripts/check_*.py`),
not vendored or reimplemented for testing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
