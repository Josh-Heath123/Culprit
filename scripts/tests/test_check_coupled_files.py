"""Unit tests for scripts/check_coupled_files.py (Phase 22,
docs/AI_NATIVE_PLAN.md). Tests the pure check() function directly with a
synthetic pairs list -- the four behaviors the phase's own Tests section
calls for -- plus one integration check that the real
scripts/coupled_files.yaml parses and contains the one pairing this
phase seeds it with.
"""

from pathlib import Path

import check_coupled_files as cf

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_both_sides_changed_passes() -> None:
    assert cf.check({"a", "b"}, [("a", "b")]) == []


def test_one_side_changed_fails_naming_the_missing_side() -> None:
    errors = cf.check({"a"}, [("a", "b")])
    assert len(errors) == 1
    assert "a" in errors[0]
    assert "b" in errors[0]


def test_other_side_changed_fails_naming_the_missing_side() -> None:
    errors = cf.check({"b"}, [("a", "b")])
    assert len(errors) == 1
    assert "a" in errors[0]
    assert "b" in errors[0]


def test_neither_side_changed_passes_trivially() -> None:
    assert cf.check(set(), [("a", "b")]) == []


def test_unrelated_change_does_not_trigger_a_declared_pair() -> None:
    assert cf.check({"c"}, [("a", "b")]) == []


def test_multiple_pairs_are_checked_independently() -> None:
    errors = cf.check({"a", "c"}, [("a", "b"), ("c", "d")])
    assert len(errors) == 2


def test_real_coupled_files_yaml_declares_the_seeded_pair() -> None:
    pairs = cf._load_pairs()
    assert ("worker/app/db.py", "api/app/db/models.py") in pairs
