"""Voyage AI embedding calls for Phase 6 (RAG retrieval).

The only module in app.rag that talks to Voyage. voyage-4's default
output dimension is 1024, matching the pgvector column defined in Phase 1
(api/app/db/models.py::Postmortem.embedding, api/migrations/versions/
e3f8d40026c9_create_core_schema.py) — see docs/IMPLEMENTATION_PLAN.md
Section 7 on why voyage-4, not voyage-3.x (only voyage-4+ carries a free
token allocation).
"""

import os

# voyageai/__init__.py imports AsyncClient without re-exporting it (no
# __all__), so pyright's reportPrivateImportUsage flags `voyageai.AsyncClient`
# even though it's the SDK's documented public entry point — importing
# from the submodule directly satisfies the type checker without a blanket
# ignore.
from voyageai.client_async import AsyncClient

EMBEDDING_MODEL = "voyage-4"
EMBEDDING_DIMENSION = 1024

_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = AsyncClient(api_key=os.environ["VOYAGE_API_KEY"])
    return _client


async def embed_document(text: str) -> list[float]:
    """input_type="document" — for text being stored/indexed (postmortems,
    see worker/scripts/seed_postmortems.py)."""
    result = await _get_client().embed([text], model=EMBEDDING_MODEL, input_type="document")
    # embeddings is typed as list[float] | list[int] (Voyage also supports
    # quantized int8/binary output dtypes); this module never requests
    # one, so the values are always float, but pyright can't narrow that
    # from the SDK's own broader return type.
    return [float(x) for x in result.embeddings[0]]


async def embed_query(text: str) -> list[float]:
    """input_type="query" — for text used to search the index (an
    incident summary looking for similar past postmortems). Voyage's
    document/query embeddings are optimized asymmetrically even for the
    same model, so this is deliberately not the same call as
    embed_document with a different label."""
    result = await _get_client().embed([text], model=EMBEDDING_MODEL, input_type="query")
    return [float(x) for x in result.embeddings[0]]
