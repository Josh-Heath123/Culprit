"""Sets a dummy MCP_READER_DATABASE_URL before any test module is
collected -- mcp_server/config.py reads it at import time with no
default (Known Trap 3: fail loudly on missing config), so importing
mcp_server.tools during test collection needs *something* set, real
value or not. The real, per-test container URL each test actually talks
to comes from its own `engine`/`mcp_reader_url` fixture, not this value
-- config.py's own MCP_READER_DATABASE_URL is only ever read once, at
import time, by mcp_server/server.py's lifespan (unused here, since
tests build engines directly).
"""

import os

os.environ.setdefault(
    "MCP_READER_DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost:5432/unused"
)
