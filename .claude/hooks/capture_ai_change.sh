#!/usr/bin/env bash
# PostToolUse hook (matcher: Bash) -- Phase 21, docs/AI_NATIVE_PLAN.md.
#
# Fires on every Bash tool call in a Claude Code session using this repo,
# not just `git commit` ones -- the substring check below must run
# before any subprocess spawn or network call, or every single shell
# command in every session gets measurably slower (Known Trap 3).
#
# Never blocks or fails the commit itself: every failure path here logs
# to stderr and exits 0, not 2. Losing one memory record (API down, a
# network blip, AGENT_AUTOMATION_TOKEN not yet configured) is a real but
# recoverable gap -- blocking every commit on this endpoint's own
# availability would be a worse failure mode than the cold-start problem
# this phase exists to fix.
set -uo pipefail

# Prefer python3 (the correct name on a real Linux deployment); this
# repo's own Windows dev environment only has a working `python` on
# PATH -- `python3` resolves to a Windows Store install-stub that exits
# nonzero the moment it's actually invoked, not merely absent, so
# `command -v` alone isn't enough to detect it. Probe by actually running
# each candidate.
PYTHON_BIN=""
for candidate in python3 python; do
  if "$candidate" -c "" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "capture_ai_change: no working python interpreter found (tried python3, python), skipping" >&2
  exit 0
fi

STDIN_JSON="$(cat)"

COMMAND="$(printf '%s' "$STDIN_JSON" | "$PYTHON_BIN" -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print('')
else:
    print(data.get('tool_input', {}).get('command', ''))
" 2>/dev/null)"

case "$COMMAND" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 0

SHA="$(git rev-parse HEAD 2>/dev/null)" || exit 0
SUMMARY="$(git log -1 --format=%B "$SHA" 2>/dev/null)" || exit 0
GIT_AUTHOR="$(git log -1 --format='%an <%ae>' "$SHA" 2>/dev/null)"
COMMITTED_AT="$(git log -1 --format=%aI "$SHA" 2>/dev/null)"
# The same file set `git show --stat` would report, without parsing that
# command's human-formatted (terminal-width-sensitive, path-truncating)
# columnar output -- git diff-tree's --name-only gives the plain list
# directly. --root is required or a repo's first (parentless) commit
# silently reports zero files changed, since diff-tree has nothing to
# diff against otherwise.
FILES_LIST="$(git diff-tree --no-commit-id --name-only -r --root "$SHA" 2>/dev/null)"

if [ -z "${AGENT_AUTOMATION_TOKEN:-}" ]; then
  echo "capture_ai_change: AGENT_AUTOMATION_TOKEN not set, skipping commit $SHA (see docs/INSTALL.md / scripts/bootstrap_env.py)" >&2
  exit 0
fi

CULPRIT_API_URL="${CULPRIT_API_URL:-http://localhost:8000}"

PAYLOAD="$("$PYTHON_BIN" -c '
import json, sys
sha, summary, git_author, committed_at, files_raw = sys.argv[1:6]
files = [line for line in files_raw.splitlines() if line.strip()]
print(json.dumps({
    "commit_sha": sha,
    "summary": summary,
    "files_changed": files,
    "git_author": git_author or None,
    "committed_at": committed_at,
}))
' "$SHA" "$SUMMARY" "$GIT_AUTHOR" "$COMMITTED_AT" "$FILES_LIST" 2>/dev/null)"

if [ -z "$PAYLOAD" ]; then
  echo "capture_ai_change: failed to build payload for commit $SHA, skipping" >&2
  exit 0
fi

RESPONSE_FILE="$(mktemp)"
HTTP_STATUS="$(curl -s -o "$RESPONSE_FILE" -w '%{http_code}' \
  -X POST "$CULPRIT_API_URL/ai-change-records" \
  -H "Authorization: Bearer $AGENT_AUTOMATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  --max-time 5 2>/dev/null)"
rm -f "$RESPONSE_FILE"

case "$HTTP_STATUS" in
  200|201) : ;;
  *)
    echo "capture_ai_change: POST /ai-change-records returned HTTP $HTTP_STATUS for commit $SHA (non-fatal)" >&2
    ;;
esac

exit 0
