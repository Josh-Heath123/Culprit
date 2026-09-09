"""Tests for the scan-coverage checker itself (standing invariant 9).

A checker that cannot fail is not a gate, and a *coverage* checker that
cannot fail is the worst version of that — it certifies every other gate.
So the cases below are mostly about making it fail on purpose: an
uncovered file, a stale root list, a directory that claimed to have no
Python and then grew some.

The second job here is keeping the two places `ruff`'s roots are written
down in agreement. `check_scan_coverage.py` parses them out of the
`justfile`; CI runs its own copy of the same commands. If those two
drift, the coverage check is measuring a command CI does not run —
which is exactly the "green gate that never read the file" failure this
invariant exists to stop, one level up.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_scan_coverage as coverage  # noqa: E402


def test_the_repository_is_fully_covered() -> None:
    """The check passes as the repository stands. If this fails, some
    Python file is read by no repo-wide check — fix the roots, do not
    relax this."""
    assert coverage.main() == 0


def test_every_registered_check_reports_real_roots() -> None:
    for name, load_roots in coverage.REPO_WIDE_CHECKS.items():
        roots = load_roots()
        assert roots, f"{name} declares no roots at all"
        for root in roots:
            assert (ROOT / root).is_dir(), f"{name} declares a root that does not exist: {root}"


def test_ruff_roots_come_from_the_justfile_not_a_copy() -> None:
    """The roots must be *parsed*, so they cannot drift from what runs.

    Asserted by changing the justfile in a temporary copy and checking
    the parsed answer changes with it — a hardcoded list would not.
    """
    roots = coverage._ruff_roots()
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    for root in roots:
        # Every parsed root traces back to a real path in a real recipe.
        assert root in justfile or Path(root).name in justfile


def test_ci_runs_the_same_ruff_roots_as_the_justfile() -> None:
    """CI is a second place the ruff invocation is written down. If it
    and the justfile disagree, one of them is not what gets checked."""
    workflow = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")

    def invocations(text: str) -> set[str]:
        return {
            # Normalise `(cd api && uv run ruff check . ../shared)` and
            # `- run: cd api && uv run ruff check . ../shared` to the
            # same comparable string.
            re.sub(r"\s+", " ", line.strip().strip("()").removeprefix("- run:").strip())
            for line in text.splitlines()
            if "ruff check" in line and not line.strip().startswith("#")
        }

    assert invocations(workflow) == invocations(justfile)


def test_an_uncovered_file_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutation that matters: shrink a check's roots and the
    coverage check must go red."""
    monkeypatch.setitem(
        coverage.REPO_WIDE_CHECKS, "deliberately narrow", lambda: ("scripts",)
    )
    assert coverage.main() == 1


def test_a_check_whose_roots_cannot_be_read_exits_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`NOT RUN` is not `PASSED`. A check whose roots cannot be loaded
    must exit 2, distinct from both the clean and the failing case."""

    def broken() -> tuple[str, ...]:
        raise coverage.Gap("simulated: roots unreadable")

    monkeypatch.setitem(coverage.REPO_WIDE_CHECKS, "broken", broken)
    assert coverage.main() == 2


def test_a_python_free_directory_that_grows_python_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_NO_PYTHON` is a promise, not a mute button. Claiming `api/` has
    no Python must fail rather than silently excusing 100-odd files."""
    monkeypatch.setitem(coverage._NO_PYTHON, "api", "deliberately wrong, for this test")
    assert coverage.main() == 1


def test_no_python_entries_all_carry_a_reason() -> None:
    """An exclusion nobody wrote a reason for is indistinguishable from
    an oversight — which is the entire problem invariant 9 names."""
    for name, reason in coverage._NO_PYTHON.items():
        assert reason.strip(), f"{name} is excluded with no stated reason"
        assert len(reason) > 10, f"{name}'s reason is too thin to review: {reason!r}"


def test_every_exclusion_carries_a_real_reason() -> None:
    """Phase 28's `_EXCLUDED` must not become a dumping ground.

    The whole premise of this script is that an unexamined exclusion is
    indistinguishable from an oversight, so an entry with no reason — or
    a reason too short to be one — defeats it. Asserted rather than
    trusted, because `check_scan_coverage.py`'s own comment promises this
    test exists.
    """
    assert coverage._EXCLUDED, "the exclusion map is empty; drop the mechanism"
    for path, reason in coverage._EXCLUDED.items():
        assert (ROOT / path).is_dir(), f"_EXCLUDED names a directory that does not exist: {path}"
        assert len(reason.strip()) > 40, (
            f"_EXCLUDED[{path!r}] has no real reason. An exclusion nobody wrote a "
            "reason for is indistinguishable from an oversight, which is the "
            "problem this script exists to solve."
        )


def test_an_excluded_directorys_python_is_really_skipped() -> None:
    """The exclusion does what it says: those files are not measured.

    Without this, `_EXCLUDED` could be silently ineffective and the check
    would still pass — for the wrong reason, since the roots happen to
    cover everything else.
    """
    files = {path.relative_to(ROOT).as_posix() for path in coverage._repo_python_files()}
    assert files, "no Python files found at all"
    for prefix in coverage._EXCLUDED:
        offending = [name for name in files if name.startswith(prefix + "/")]
        assert not offending, f"{prefix} is in _EXCLUDED but its files are still measured"
    # And the exclusion is not so broad it swallowed the repository.
    assert len(files) > 100, f"only {len(files)} files measured; an exclusion is too broad"


def test_a_new_exclusion_cannot_hide_an_uncovered_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation that matters for `_EXCLUDED` itself.

    Remove the fixture exclusion and the fixture corpus — real Python
    that no check reads — must make the coverage check fail. If it does
    not, the exclusion is not load-bearing and something else is quietly
    covering those files.
    """
    monkeypatch.setattr(coverage, "_EXCLUDED", {})
    assert coverage.main() == 1


def test_the_stop_hook_excludes_exactly_what_this_checker_does() -> None:
    """`.claude/hooks/fast_gates.sh` lints changed Python on every turn.

    It has to skip the same paths this checker excludes, or the hook
    reformats vendored upstream source to satisfy our import style — and
    a third-party fixture that has been reformatted is no longer a
    third-party fixture, which is the only property that makes it worth
    having.

    The hook is bash and cannot import this module, so the list is
    duplicated there. Parsed rather than restated here, so the two cannot
    drift — the same technique `_ruff_roots` uses on the justfile, and
    for the same reason: the copy that *runs* is the one that has to be
    checked.
    """
    hook = ROOT / ".claude" / "hooks" / "fast_gates.sh"
    assert hook.is_file(), f"the stop hook is missing: {hook}"

    match = re.search(r"^EXCLUDED_PREFIXES='([^']*)'", hook.read_text(encoding="utf-8"), re.M)
    assert match, "fast_gates.sh has no EXCLUDED_PREFIXES assignment to check"

    hook_prefixes = {prefix for prefix in match.group(1).split() if prefix}
    checker_prefixes = {prefix.rstrip("/") + "/" for prefix in coverage._EXCLUDED}
    assert hook_prefixes == checker_prefixes, (
        f"the stop hook excludes {sorted(hook_prefixes)} but this checker excludes "
        f"{sorted(checker_prefixes)} — one of them is linting something the other "
        "has decided must not be linted"
    )
