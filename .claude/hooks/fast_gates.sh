#!/usr/bin/env bash
# Stop hook: run the fast deterministic gates before Claude is allowed to
# finish its turn. Exit 2 feeds stderr back into the session as actionable
# context, so "I've implemented it" becomes "show me it actually works" —
# the same evidence-before-assertion rule this product is being built to
# enforce, applied to its own development loop.
#
# Deliberately fast (target < 5s). The slow gates — pytest, pyright,
# check_schema_drift (which shells out to two separate uv venvs) — belong
# in the /verify skill, invoked on purpose. A Stop hook that runs the full
# suite on every turn makes the session unusable, and a hook people disable
# enforces nothing.
#
# Loop guard: a Stop hook that exits 2 forever would trap the session. This
# blocks at most MAX_BLOCKS times per session, keyed on session_id, then
# lets the turn end with the failure reported but not enforced.

set -uo pipefail

MAX_BLOCKS=2
REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$REPO_ROOT" ] && [ -d "$REPO_ROOT" ] || exit 0
cd "$REPO_ROOT" || exit 0

payload="$(cat)"

# session_id is used only to scope the loop guard; a missing one degrades to
# a single shared counter rather than failing the hook.
session_id="$(printf '%s' "$payload" \
  | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' \
  | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
session_id="${session_id:-nosession}"

counter_dir="${TMPDIR:-/tmp}/culprit-fast-gates"
mkdir -p "$counter_dir" 2>/dev/null || exit 0
counter_file="$counter_dir/$session_id"
blocks="$(cat "$counter_file" 2>/dev/null || echo 0)"
case "$blocks" in ''|*[!0-9]*) blocks=0 ;; esac
[ "$blocks" -ge "$MAX_BLOCKS" ] && exit 0

command -v uv >/dev/null 2>&1 || exit 0

# Changed + untracked files, CR-stripped: this repo has no .gitattributes,
# so on Windows checkouts git output can carry stray carriage returns that
# break suffix matching (the same bug already fixed in check_invariants.sh).
changed="$( { git diff --name-only --diff-filter=ACM 2>/dev/null
              git diff --name-only --diff-filter=ACM --cached 2>/dev/null
              git ls-files --others --exclude-standard 2>/dev/null
            } | tr -d '\r' | sort -u )"
[ -n "$changed" ] || exit 0

# Paths whose Python is deliberately outside every repo-wide check.
# Authoritative copy: scripts/check_scan_coverage.py's _EXCLUDED, which
# carries the reasons; scripts/tests/test_scan_coverage.py asserts this
# list matches it, so the two cannot drift.
#
# The fixture corpus is the whole of it. Two of its projects are vendored
# verbatim from upstream at a pinned tag, and reformatting somebody else's
# source to satisfy our import style turns a third-party fixture back into
# one of ours — destroying the only property that makes it worth having
# (cli/testdata/fixtures/README.md). The author-written fixtures are
# excluded for the same reason: they are samples of what real code looks
# like, and a lint pass would change what is being tested.
#
# This is the one place the hook is deliberately *less* strict than a
# naive "lint every changed .py". The justfile's note about the hook once
# being stricter than the gate was about the gate being too narrow; here
# the gate is narrow on purpose and the hook follows it.
EXCLUDED_PREFIXES='cli/testdata/fixtures/ cli/testdata/demo/'

# One `grep -v -F -e <prefix>` per entry, built up rather than passing
# the whole string as a single pattern: with two prefixes,
# `-e "$EXCLUDED_PREFIXES"` would look for the literal
# "cli/testdata/fixtures/ cli/testdata/demo/", match nothing, and
# silently start linting both fixture corpora again.
exclude_args=""
for prefix in $EXCLUDED_PREFIXES; do
  exclude_args="$exclude_args -e $prefix"
done

py_files="$(printf '%s\n' "$changed" | grep '\.py$' \
  | grep -v -F $exclude_args || true)"
migrations="$(printf '%s\n' "$py_files" | grep '^api/migrations/versions/' || true)"

failures=""

if [ -n "$py_files" ]; then
  # shellcheck disable=SC2086
  if ! out="$(uv run --project api ruff check $py_files 2>&1)"; then
    failures="${failures}ruff:\n${out}\n\n"
  fi
fi

if ! out="$(uv run --project api python "$REPO_ROOT/scripts/check_coupled_files.py" 2>&1)"; then
  failures="${failures}coupled-files:\n${out}\n\n"
fi

if [ -n "$migrations" ]; then
  # shellcheck disable=SC2086
  if ! out="$(uv run --project api python "$REPO_ROOT/scripts/check_migration_symmetry.py" $migrations 2>&1)"; then
    failures="${failures}migration-symmetry:\n${out}\n\n"
  fi
fi

if [ -n "$failures" ]; then
  echo $((blocks + 1)) > "$counter_file"
  {
    echo "Fast gates failed — fix these before finishing the turn:"
    echo
    printf '%b' "$failures"
    echo "(Blocked $((blocks + 1))/$MAX_BLOCKS times this session. Run /verify for the full gate set.)"
  } >&2
  exit 2
fi

rm -f "$counter_file" 2>/dev/null
exit 0
