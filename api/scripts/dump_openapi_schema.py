"""Dumps the FastAPI app's OpenAPI schema to stdout as JSON.

No live server needed — app.openapi() only introspects registered
routes and Pydantic models, it never touches the lifespan (DB engine,
Redis pool). Feeds frontend's `npm run generate-types` (openapi-typescript,
see frontend/package.json), which regenerates
frontend/src/lib/api-types.generated.ts from this — the fix for
frontend/src/lib/types.ts having been a hand-maintained, silently
driftable mirror of api/app/incidents/schemas.py (Phase 11 P1).
"""

import json

from app.main import app

print(json.dumps(app.openapi()))
