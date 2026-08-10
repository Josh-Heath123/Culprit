"""Entry point for `uv run --project mcp_server python -m mcp_server`
(run from the repo root, matching the existing `uv run --project api
python scripts/check_*.py` convention already used throughout this repo
-- see docs/AI_NATIVE_INSTRUMENTATION.md). Stdio transport, matching
every other local-only tool in this project (Out of scope: no shared,
multi-client deployment here).
"""

from .server import mcp

if __name__ == "__main__":
    mcp.run()
