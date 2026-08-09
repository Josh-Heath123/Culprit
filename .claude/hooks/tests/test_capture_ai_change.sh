#!/usr/bin/env bash
# Shell-level test for .claude/hooks/capture_ai_change.sh (Phase 21,
# docs/AI_NATIVE_PLAN.md's own Tests section calls for exactly this: a
# synthetic stdin JSON payload against a real throwaway git repo,
# asserting the API call shape without a live Claude Code session or a
# real API server. The live-session, real-server path is the "verified
# live" acceptance criterion, checked separately, not by this script.
#
# Fakes `curl` (a tiny script placed first on PATH that records its own
# argv instead of making a real HTTP call) so this test needs no running
# api process. Everything else the hook touches -- git, python -- is the
# real thing, run against a disposable repo under a temp directory.
#
# Run directly: bash .claude/hooks/tests/test_capture_ai_change.sh
# Exits 0 if every assertion passes, 1 on the first failure.
set -uo pipefail

HOOK_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/capture_ai_change.sh"
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

assert_not_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) fail "$label -- expected NOT to find: $needle" ;;
    *) ;;
  esac
}

assert_file_exists() {
  [ -f "$1" ] || fail "$2 -- expected file to exist: $1"
}

assert_file_absent() {
  [ -f "$1" ] && fail "$2 -- expected file NOT to exist: $1"
  return 0
}

# --- fake curl -------------------------------------------------------------
# Records every argument it was called with to CURL_CAPTURE_FILE (one per
# line, so a payload containing spaces/quotes stays intact) and prints a
# fake "200" the way `curl -w '%{http_code}'` would, so the hook's own
# `case "$HTTP_STATUS" in 200|201) ;; ...` branch treats it as success.
FAKE_BIN_DIR="$WORKDIR/fakebin"
mkdir -p "$FAKE_BIN_DIR"
cat >"$FAKE_BIN_DIR/curl" <<'EOF'
#!/usr/bin/env bash
: > "$CURL_CAPTURE_FILE"
for arg in "$@"; do
  printf '%s\n' "$arg" >> "$CURL_CAPTURE_FILE"
done
# honor -o <file> so the hook's later `rm -f` has something real to remove
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    : > "$arg"
  fi
  prev="$arg"
done
echo -n "200"
EOF
chmod +x "$FAKE_BIN_DIR/curl"

# --- throwaway git repo ------------------------------------------------
REPO="$WORKDIR/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.name "Test User"
git -C "$REPO" config user.email "test@example.com"
echo "hello" > "$REPO/file.txt"
git -C "$REPO" add file.txt
git -C "$REPO" commit -q -m "Add file.txt"
EXPECTED_SHA="$(git -C "$REPO" rev-parse HEAD)"

run_hook() {
  local command_json="$1"
  ( cd "$REPO" && printf '%s' "$command_json" | PATH="$FAKE_BIN_DIR:$PATH" bash "$HOOK_SCRIPT" )
}

# --- Test 1: git commit command, token set -> curl called with the right shape
CURL_CAPTURE_FILE="$WORKDIR/curl_call_1.txt"
export CURL_CAPTURE_FILE
export AGENT_AUTOMATION_TOKEN="test-token-123"
export CULPRIT_API_URL="http://fake-api.invalid"

STDIN='{"tool_name": "Bash", "tool_input": {"command": "git commit -m \"Add file.txt\""}}'
run_hook "$STDIN"
HOOK_EXIT=$?

[ "$HOOK_EXIT" -eq 0 ] || fail "Test 1: hook should exit 0, got $HOOK_EXIT"
assert_file_exists "$CURL_CAPTURE_FILE" "Test 1"
if [ -f "$CURL_CAPTURE_FILE" ]; then
  CAPTURED="$(cat "$CURL_CAPTURE_FILE")"
  assert_contains "$CAPTURED" "http://fake-api.invalid/ai-change-records" "Test 1: URL"
  assert_contains "$CAPTURED" "Authorization: Bearer test-token-123" "Test 1: auth header"
  assert_contains "$CAPTURED" "Content-Type: application/json" "Test 1: content-type header"
  assert_contains "$CAPTURED" "\"commit_sha\": \"$EXPECTED_SHA\"" "Test 1: commit_sha"
  assert_contains "$CAPTURED" "\"files_changed\": [\"file.txt\"]" "Test 1: files_changed"
  assert_contains "$CAPTURED" "Add file.txt" "Test 1: summary"
  assert_contains "$CAPTURED" "\"git_author\": \"Test User <test@example.com>\"" "Test 1: git_author"
fi

# --- Test 2: non-commit command -> curl must never be invoked
CURL_CAPTURE_FILE="$WORKDIR/curl_call_2.txt"
export CURL_CAPTURE_FILE
STDIN='{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}'
run_hook "$STDIN"
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 2: hook should exit 0, got $HOOK_EXIT"
assert_file_absent "$CURL_CAPTURE_FILE" "Test 2: non-commit command must not call curl"

# --- Test 3: git commit, but AGENT_AUTOMATION_TOKEN unset -> curl must never be invoked
CURL_CAPTURE_FILE="$WORKDIR/curl_call_3.txt"
export CURL_CAPTURE_FILE
unset AGENT_AUTOMATION_TOKEN
STDIN='{"tool_name": "Bash", "tool_input": {"command": "git commit -m \"Add file.txt\""}}'
STDERR_OUTPUT="$(run_hook "$STDIN" 2>&1 1>/dev/null)"
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 3: hook should exit 0, got $HOOK_EXIT"
assert_file_absent "$CURL_CAPTURE_FILE" "Test 3: missing token must not call curl"
assert_contains "$STDERR_OUTPUT" "AGENT_AUTOMATION_TOKEN not set" "Test 3: stderr message"

# --- Test 4: malformed stdin JSON -> hook exits 0, no crash, no curl call
export AGENT_AUTOMATION_TOKEN="test-token-123"
CURL_CAPTURE_FILE="$WORKDIR/curl_call_4.txt"
export CURL_CAPTURE_FILE
run_hook 'not valid json at all'
HOOK_EXIT=$?
[ "$HOOK_EXIT" -eq 0 ] || fail "Test 4: hook should exit 0 on malformed stdin, got $HOOK_EXIT"
assert_file_absent "$CURL_CAPTURE_FILE" "Test 4: malformed stdin must not call curl"

if [ "$FAILURES" -eq 0 ]; then
  echo "All capture_ai_change.sh tests passed."
  exit 0
else
  echo "$FAILURES test(s) failed." >&2
  exit 1
fi
