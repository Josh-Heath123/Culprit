"""Startup configuration for the Culprit MCP server (Phase 24,
docs/AI_NATIVE_PLAN.md). Fails loudly and immediately on missing config,
matching every existing `_require_env`-style pattern already used
throughout `api/migrations/versions/` and `scripts/bootstrap_env.py`
(Known Trap 3) -- a stdio server that fails obscurely deep inside a tool
call instead of at startup, with no env var set, is a much worse
debugging experience for whoever registers it in their own session.

VOYAGE_API_KEY is deliberately *not* validated here: `_embed_query`
(tools.py) mirrors worker/app/rag/embeddings.py's own lazy read (only
checked the first time an embedding call actually happens), since this
is a duplicated copy of that exact function, not a redesign of it
(Known Trap 1).
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Phase 22's declared "must change together" registry -- read directly
#: as a data file, not imported from scripts/check_coupled_files.py's own
#: Python code. scripts/ isn't a uv project of its own (no path
#: dependency to add), but importing another project's *module* is
#: exactly the cross-project coupling Known Trap 1 warns against; reading
#: a shared, repo-root-relative YAML config file both tools happen to
#: read is a different, much lower-risk kind of sharing.
COUPLED_FILES_YAML = REPO_ROOT / "scripts" / "coupled_files.yaml"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} must be set in the environment to run the Culprit MCP server "
            "-- see docs/AI_NATIVE_INSTRUMENTATION.md"
        )
    return value


MCP_READER_DATABASE_URL = _require_env("MCP_READER_DATABASE_URL")
