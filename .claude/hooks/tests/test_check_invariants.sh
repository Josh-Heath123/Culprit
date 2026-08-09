#!/usr/bin/env bash
# Shell-level test for .claude/hooks/check_invariants.sh (Phase 22,
# docs/AI_NATIVE_PLAN.md's own Tests section calls for exactly this
# pattern, matching Phase 21's test_capture_ai_change.sh: synthetic
# stdin JSON against a real throwaway git repo, asserting exit code and
# stderr content without a live Claude Code session).
#
# Unlike capture_ai_change.sh, this hook's real logic lives almost
# entirely in the two Python scripts it shells out to
# (`uv run --project api python scripts/check_*.py`) -- scripts that
# only exist, and only work, inside *this* actual repo, not a throwaway
# test one. So this test fakes `uv` (a tiny script placed first on PATH
# that records its own argv and returns a controllable exit code/output
# instead of actually invoking either script) to test the *hook's own*
# logic in isolation: JSON parsing, the file_path-under-migrations/
# versions/ decision, always-run-coupled-check, error aggregation, and
# translating any failure into exit 2 + stderr. The two check scripts'
# own correctness is proven separately by scripts/tests/
# test_check_migration_symmetry.py and test_check_coupled_files.py, and
# by this phase's own live verification against the real repo.
#
# Run directly: bash .claude/hooks/tests/test_check_invariants.sh
# Exits 0 if every assertion passes, 1 on the first failure.
set -uo pipefail

HOOK_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/check_invariants.sh"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

FAILURES=0

fail() {
  echo "FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) ;;
    *) fail "$label -- expected to find: $needle" ;;
  esac
}

# --- fake uv -----------------------------------------------------------
FAKE_BIN_DIR="$WORKDIR/fakebin"
mkdir -p "$FAKE_BIN_DIR"
cat >"$FAKE_BIN_DIR/uv" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$UV_CALLS_FILE"
case "$*" in
  *check_coupled_files.py*)
    if [ "${FAKE_COUPLED_EXIT:-0}" -ne 0 ]; then
      echo "FAKE COUPLED VIOLATION" >&2
      exit "${FAKE_COUPLED_EXIT}"
    fi
    echo "No coupled-file violations across 1 declared pair(s)."
    exit 0
    ;;
  *check_migration_symmetry.py*)
    if [ "${FAKE_SYMMETRY_EXIT:-0}" -ne 0 ]; then
      echo "FAKE SYMMETRY VIOLATION" >&2
      exit "${FAKE_SYMMETRY_EXIT}"
    fi
    echo "No migration symmetry violations across 1 file(s)."
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
chmod +x "$FAKE_BIN_DIR/uv"

# --- throwaway git repo (just needs to exist for `git rev-parse
# --show-toplevel` to succeed -- the hook never reads its content) -----
REPO="$WORKDIR/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.name "Test User"
git -C "$REPO" config user.email "test@example.com"

run_hook() {
  local file_path="$1"
  # Built via python's own json.dumps, not hand-rolled string
  # interpolation -- a Windows path (Test 5) contains raw backslashes,
  # and embedding those into a JSON string literally without escaping
  # produces invalid JSON, not a realistic payload. A real Claude Code
  # hook invocation serializes this the same way (a real JSON encoder),
  # so this matches that instead of accidentally testing malformed input.
  local payload
  payload="$(python -c "
import json, sys
print(json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': sys.argv[1]}}))
" "$file_path")"
  ( cd "$REPO" && printf '%s' "$payload" | PATH="$FAKE_BIN_DIR:$PATH" bash "$HOOK_SCRIPT" )
}

# --- Test 1: non-migration file, both checks (well, just the coupled
# one -- symmetry never runs) pass -> exit 0, uv called exactly once
UV_CALLS_FILE="$WORKDIR/calls_1.txt"
export UV_CALLS_FILE
export FAKE_COUPLED_EXIT=0
STDERR_OUTPUT="$(run_hook "$REPO/some/file.py" 2>&1 1>/dev/null)"
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 1: expected exit 0, got $HOOK_EXIT"
CALL_COUNT="$(wc -l < "$UV_CALLS_FILE" | tr -d ' ')"
[ "$CALL_COUNT" = "1" ] || fail "Test 1: expected exactly 1 uv call, got $CALL_COUNT"
assert_contains "$(cat "$UV_CALLS_FILE")" "check_coupled_files.py" "Test 1: calls coupled check"

# --- Test 2: non-migration file, coupled check fails -> exit 2, stderr
# carries the fake violation text, symmetry never runs (still 1 call)
UV_CALLS_FILE="$WORKDIR/calls_2.txt"
export UV_CALLS_FILE
export FAKE_COUPLED_EXIT=1
STDERR_OUTPUT="$(run_hook "$REPO/some/file.py" 2>&1 1>/dev/null)"
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 2 ] || fail "Test 2: expected exit 2, got $HOOK_EXIT"
assert_contains "$STDERR_OUTPUT" "FAKE COUPLED VIOLATION" "Test 2: stderr"
CALL_COUNT="$(wc -l < "$UV_CALLS_FILE" | tr -d ' ')"
[ "$CALL_COUNT" = "1" ] || fail "Test 2: expected exactly 1 uv call, got $CALL_COUNT"
unset FAKE_COUPLED_EXIT

# --- Test 3: a migration file, both checks pass -> exit 0, uv called
# twice (coupled always, symmetry because the path matches)
UV_CALLS_FILE="$WORKDIR/calls_3.txt"
export UV_CALLS_FILE
run_hook "$REPO/api/migrations/versions/some_migration.py" >/dev/null 2>&1
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 3: expected exit 0, got $HOOK_EXIT"
CALL_COUNT="$(wc -l < "$UV_CALLS_FILE" | tr -d ' ')"
[ "$CALL_COUNT" = "2" ] || fail "Test 3: expected exactly 2 uv calls, got $CALL_COUNT"
assert_contains "$(cat "$UV_CALLS_FILE")" "check_migration_symmetry.py" "Test 3: calls symmetry check"

# --- Test 4: a migration file, symmetry check fails -> exit 2, stderr
# carries the fake violation text
UV_CALLS_FILE="$WORKDIR/calls_4.txt"
export UV_CALLS_FILE
export FAKE_SYMMETRY_EXIT=1
STDERR_OUTPUT="$(run_hook "$REPO/api/migrations/versions/some_migration.py" 2>&1 1>/dev/null)"
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 2 ] || fail "Test 4: expected exit 2, got $HOOK_EXIT"
assert_contains "$STDERR_OUTPUT" "FAKE SYMMETRY VIOLATION" "Test 4: stderr"
unset FAKE_SYMMETRY_EXIT

# --- Test 5: a migration file referenced with a Windows backslash path
# (this project's own dev environment reality) still triggers the
# symmetry check -- regression coverage for the CRLF/backslash
# normalization bug this phase's own live testing caught.
UV_CALLS_FILE="$WORKDIR/calls_5.txt"
export UV_CALLS_FILE
WINDOWS_STYLE_PATH="$(printf '%s' "$REPO/api/migrations/versions/some_migration.py" | tr '/' '\\')"
run_hook "$WINDOWS_STYLE_PATH" >/dev/null 2>&1
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 5: expected exit 0, got $HOOK_EXIT"
CALL_COUNT="$(wc -l < "$UV_CALLS_FILE" | tr -d ' ')"
[ "$CALL_COUNT" = "2" ] || fail "Test 5: expected exactly 2 uv calls (backslash path), got $CALL_COUNT"

if [ "$FAILURES" -eq 0 ]; then
  echo "All check_invariants.sh tests passed."
  exit 0
else
  echo "$FAILURES test(s) failed." >&2
  exit 1
fi
