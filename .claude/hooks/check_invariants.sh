#!/usr/bin/env bash
# PostToolUse hook (matcher: Edit|Write) -- Phase 22, docs/AI_NATIVE_PLAN.md.
#
# Fires *after* the tool already wrote the file (verified against
# Claude Code's current hooks documentation: PostToolUse cannot refuse a
# write, unlike a PreToolUse hook) -- this does not prevent a bad edit,
# it surfaces the violation immediately after, in the same turn, instead
# of at review time. The just-edited file is left exactly as written;
# the agent's own next move (fix the paired file, or the migration) is
# what actually resolves it.
#
# Always runs check_coupled_files.py (cheap: one `git status` plus a
# small YAML read). Only runs check_migration_symmetry.py when the
# just-edited file is under api/migrations/versions/ -- no reason to
# parse migration ASTs on every unrelated edit (this project's own docs
# under docs/ included).
#
# Exit 2 + stderr is what feeds the violation back to the agent as
# actionable context; exit 1 only logs quietly. Never blocks on its own
# infrastructure failing (no repo found, no working python) -- exits 0
# instead, same reasoning as .claude/hooks/capture_ai_change.sh: losing
# one real-time check is recoverable, CI is the actual gate either way.
set -uo pipefail

PYTHON_BIN=""
for candidate in python3 python; do
  if "$candidate" -c "" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "check_invariants: no working python interpreter found (tried python3, python), skipping" >&2
  exit 0
fi

STDIN_JSON="$(cat)"

# Two lines: the raw file_path (passed to check_migration_symmetry.py
# unchanged) and a forward-slash-normalized copy, so the `case` match
# below doesn't need to special-case a Windows backslash path.
HOOK_INFO="$(printf '%s' "$STDIN_JSON" | "$PYTHON_BIN" -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
file_path = data.get('tool_input', {}).get('file_path', '') or ''
print(file_path)
print(file_path.replace(chr(92), '/'))
" 2>/dev/null)"

mapfile -t HOOK_INFO_LINES <<< "$HOOK_INFO"
# Strip a trailing \r: on this project's Windows dev environment, native
# Windows Python's print() emits \r\n even though bash's `<<<`/mapfile
# only splits on \n, leaving a \r stuck to the end of each captured
# line. Silent and easy to miss -- a substring match (capture_ai_change.sh's
# own `case "$COMMAND" in *"git commit"*)`) tolerates it, but an exact
# comparison doesn't: an uncaught trailing \r here made `path.suffix !=
# ".py"` true for every real .py file, silently skipping every migration
# symmetry check instead of erroring loudly (caught only by testing this
# live, not by reasoning about the code).
FILE_PATH="${HOOK_INFO_LINES[0]%$'\r'}"
NORMALIZED_PATH="${HOOK_INFO_LINES[1]%$'\r'}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 0

ERRORS=""

COUPLED_OUTPUT="$(uv run --project api python scripts/check_coupled_files.py 2>&1)"
if [ $? -ne 0 ]; then
  ERRORS="${ERRORS}${COUPLED_OUTPUT}"$'\n'
fi

case "$NORMALIZED_PATH" in
  */api/migrations/versions/*)
    SYMMETRY_OUTPUT="$(uv run --project api python scripts/check_migration_symmetry.py "$FILE_PATH" 2>&1)"
    if [ $? -ne 0 ]; then
      ERRORS="${ERRORS}${SYMMETRY_OUTPUT}"$'\n'
    fi
    ;;
esac

if [ -n "$ERRORS" ]; then
  printf '%s' "$ERRORS" >&2
  exit 2
fi

exit 0
