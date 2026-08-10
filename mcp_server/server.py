"""FastMCP application instance for the Culprit MCP server (Phase 24,
docs/AI_NATIVE_PLAN.md). Stdio transport only (Out of scope: no shared,
multi-client streamable-HTTP deployment in this phase).

Tools register themselves against `mcp` via the `@mcp.tool` decorator in
tools.py, imported at the bottom of this module -- after `mcp` exists in
this module's namespace, since tools.py itself does
`from mcp_server.server import mcp`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .config import MCP_READER_DATABASE_URL


@dataclass
class AppContext:
    engine: AsyncEngine


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """One `mcp-reader` engine for the server's whole lifetime, not one
    per tool call -- the same long-lived-engine pattern every other
    entry point in this codebase already uses (api/app/main.py,
    worker/app/main.py's own startup())."""
    engine = create_async_engine(MCP_READER_DATABASE_URL)
    try:
        yield AppContext(engine=engine)
    finally:
        await engine.dispose()


mcp = FastMCP("culprit_mcp", lifespan=app_lifespan)

from . import tools  # noqa: E402,F401
