#!/usr/bin/env python3
"""Fails if a file declared in scripts/coupled_files.yaml as "must
change together with" another file changed alone (Phase 22,
docs/AI_NATIVE_PLAN.md) -- generalizes the one hardcoded pairing
scripts/check_schema_drift.py already enforces (worker/app/db.py <->
api/app/db/models.py) into a declarable list, so a future pairing needs
only a new line in that YAML file, not a new script.

Two modes:

- No arguments (the default): checks the *working tree's* current
  changed files (staged + unstaged + untracked, via `git status
  --porcelain`) -- what a Claude Code hook sees mid-session, before any
  commit exists (.claude/hooks/check_invariants.sh's own use). Checking
  the whole working-tree diff state, not just "did this one edit's
  paired file change in this one tool call," is deliberate: it makes
  editing both files in either order, in the same session, pass -- see
  that phase's own Known Trap 2.
- `--base <ref>`: checks `git diff --name-only <ref>...HEAD` instead --
  CI's mode (`--base origin/main`), since a CI checkout has no
  uncommitted working-tree changes to look at, only committed history to
  diff against.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COUPLED_FILES_YAML = Path(__file__).resolve().parent / "coupled_files.yaml"


def _load_pairs() -> list[tuple[str, str]]:
    data = yaml.safe_load(COUPLED_FILES_YAML.read_text())
    return [tuple(pair) for pair in data.get("pairs", [])]


def _working_tree_changed_files() -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files: set[str] = set()
    for line in result.stdout.splitlines():
        if not line or line.startswith("!!"):
            continue
        # porcelain=v1: two status chars, a space, then the path (or, for
        # a rename, "old -> new" -- the new path is what matters here).
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        files.add(path_part.strip('"'))
    return files


def _diff_against(base: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check(changed: set[str], pairs: list[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for a, b in pairs:
        a_changed, b_changed = a in changed, b in changed
        if a_changed and not b_changed:
            errors.append(f'"{a}" changed but its declared pair "{b}" did not')
        elif b_changed and not a_changed:
            errors.append(f'"{b}" changed but its declared pair "{a}" did not')
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="Compare git diff --name-only <base>...HEAD instead of the working tree (CI mode)",
    )
    args = parser.parse_args(argv)

    changed = _diff_against(args.base) if args.base else _working_tree_changed_files()
    pairs = _load_pairs()
    errors = check(changed, pairs)

    if errors:
        print("Coupled-file violations (see scripts/coupled_files.yaml):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"No coupled-file violations across {len(pairs)} declared pair(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
