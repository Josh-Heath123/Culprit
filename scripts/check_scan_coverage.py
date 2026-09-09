#!/usr/bin/env python3
"""Fails if a repo-wide check's scanned roots do not actually cover the
repository.

Standing invariant 9 (docs/DIAGNOSTIC_PLAN.md §3), added 2026-09-09:
*"Every check declares its scanned roots, and a test asserts those roots
cover the repository."*

Two blind spots surfaced in two consecutive phases. `just lint` never
covered `scripts/`. The subject-construction lint never covered
`api/tests/`, and a real hand-formatted subject URI sat inside that gap —
exempt by accident, inside a green gate. Both times the check itself was
working perfectly; it was simply not looking at the file.

**The coverage of a check is itself a thing that has to be checked.** A
green gate that never read the offending file is worse than a red one,
because it is evidence of correctness that nobody has any reason to
doubt.

So: every check that claims to apply repo-wide registers its roots here,
and this script walks the repository's actual Python files and fails on
any file no such check would read. A directory may be excluded only with
a stated reason — an exclusion nobody wrote a reason for is
indistinguishable from an oversight, which is the whole problem.

Roots are **imported from the check itself**, never re-typed here. A copy
would drift, and a coverage checker that verifies a stale copy of the
roots is precisely the kind of check-that-cannot-fail this invariant
exists to prevent.

Exit codes: 0 covered · 1 a gap · 2 could not run (a check's roots could
not be imported). 2 is distinct because "the coverage check did not run"
must never read as "coverage is fine".

Run with `just check-scan-coverage`; runs in CI beside the other checks.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Never part of any check's business: third-party code, build output,
#: caches. Matched against any path part.
_SKIPPED_PARTS = {
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}

#: Top-level directories with no Python in them, and why. Listed rather
#: than silently skipped: if `frontend/` ever grows a Python script, this
#: script fails and someone has to decide what checks it, which is the
#: correct outcome.
_NO_PYTHON: dict[str, str] = {
    "frontend": "TypeScript/React; covered by eslint and tsc, not by any Python check",
    "docs": "prose and plans; no executable code of any language",
    "infra": "Docker Compose, Caddyfile and shell; shell is reviewed, not linted",
    ".github": "workflow YAML; validated by GitHub Actions itself on push",
    ".claude": "agent configuration, rules and hooks (markdown and shell)",
}


class Gap(Exception):
    """Raised when a check's declared roots cannot be read at all."""


def _repo_python_files() -> list[Path]:
    """Every Python file in the repository, third-party code excluded."""
    return sorted(
        path
        for path in ROOT.rglob("*.py")
        if _SKIPPED_PARTS.isdisjoint(path.relative_to(ROOT).parts)
    )


def _subject_lint_roots() -> tuple[str, ...]:
    """`scripts/tests/test_subject_construction.py`'s `SCANNED`.

    Imported, not copied. The module is a pytest file but has no
    import-time side effects beyond building its file list, so importing
    it here is safe and is the only way to be sure this script is
    checking the roots the lint really uses.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "tests"))
    try:
        import test_subject_construction

        return tuple(test_subject_construction.SCANNED)
    except Exception as exc:  # pragma: no cover - import problem
        raise Gap(f"cannot read the subject-construction lint's roots: {exc}") from exc
    finally:
        sys.path.pop(0)


def _ruff_roots() -> tuple[str, ...]:
    """The directories `just lint` actually passes to ruff.

    Parsed out of the `justfile` rather than restated, for the same
    reason the subject lint's roots are imported: the justfile is what
    runs, so it is what has to be checked. `scripts/tests/test_scan_coverage.py`
    additionally asserts these match the CI workflow's own ruff steps,
    since CI is a second place the same list is written down.
    """
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    roots: set[str] = set()
    for line in justfile.splitlines():
        # Recipes are parenthesised subshells:
        #     (cd api && uv run ruff check . ../shared ../scripts)
        stripped = line.strip().strip("()")
        if "ruff check" not in stripped or stripped.startswith("#"):
            continue
        base = stripped.split("cd ", 1)[1].split(" ", 1)[0] if stripped.startswith("cd ") else "."
        for argument in stripped.split("ruff check", 1)[1].split():
            if argument.startswith("-"):
                continue
            resolved = (ROOT / base / argument).resolve()
            try:
                roots.add(resolved.relative_to(ROOT).as_posix() or ".")
            except ValueError:  # pragma: no cover - a path outside the repo
                continue
    return tuple(sorted(roots))


#: Every check that claims repo-wide reach, with the roots it declares.
#: A check with a deliberately narrow scope (`check_no_llm_imports.py`
#: names an explicit list of deterministic packages; `check_schema_drift.py`
#: compares exactly two files) is not registered here — it does not claim
#: to cover the repository, so measuring it against the repository would
#: be measuring the wrong thing.
REPO_WIDE_CHECKS = {
    "just lint (ruff)": _ruff_roots,
    "subject-construction lint": _subject_lint_roots,
}


def _covered_by(roots: tuple[str, ...], relative: str) -> bool:
    return any(relative == root or relative.startswith(root.rstrip("/") + "/") for root in roots)


def main() -> int:
    files = _repo_python_files()
    if not files:  # pragma: no cover - a checkout with no Python at all
        print("no Python files found; refusing to report coverage", file=sys.stderr)
        return 2

    # A directory declared Python-free that has since grown Python.
    broken_promises = sorted(
        {
            parts[0]
            for path in files
            if (parts := path.relative_to(ROOT).parts)[0] in _NO_PYTHON
        }
    )
    if broken_promises:
        print(
            "These directories are recorded in _NO_PYTHON as having no Python, "
            "and now do:",
            file=sys.stderr,
        )
        for name in broken_promises:
            print(f"  - {name}/ — {_NO_PYTHON[name]}", file=sys.stderr)
        print(
            "\nDecide which check covers it, add it to that check's roots, and "
            "remove the entry here.",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    for name, load_roots in sorted(REPO_WIDE_CHECKS.items()):
        try:
            roots = load_roots()
        except Gap as exc:
            print(str(exc), file=sys.stderr)
            return 2

        uncovered = [
            relative
            for path in files
            if not _covered_by(roots, (relative := path.relative_to(ROOT).as_posix()))
        ]
        if uncovered:
            failures.append(
                f"{name}: declares roots {list(roots)} but does not reach "
                f"{len(uncovered)} Python file(s):\n"
                + "\n".join(f"    {relative}" for relative in uncovered[:20])
                + ("\n    ..." if len(uncovered) > 20 else "")
            )
        else:
            print(f"{name}: covers all {len(files)} Python files (roots: {', '.join(roots)})")

    if failures:
        print("\nScan-coverage gaps:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "\nStanding invariant 9: a check that never reads a file is not a gate "
            "for that file. Widen the roots, or record the directory in "
            "_NO_PYTHON with a reason.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
