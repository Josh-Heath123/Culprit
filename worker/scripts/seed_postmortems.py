"""One-off script: embed and store Phase 6's seed postmortems.

Not part of the live job path — app/rag/job.py never imports this module
or app/rag/seed_postmortems.py. Run once via `just seed-postmortems`
(invoked as `python -m scripts.seed_postmortems` so `app` resolves as an
importable package from the worker project root — a plain
`python scripts/seed_postmortems.py` would not have `app` on sys.path).

Idempotent by title: re-running only inserts postmortems that don't
already exist and only (re-)embeds ones currently missing an embedding,
so it's safe to run again after adding a new entry to
app/rag/seed_postmortems.py without re-embedding (and re-billing) the
rest of the corpus.
"""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

from app.db import postmortems  # noqa: E402
from app.rag.embeddings import embed_document  # noqa: E402
from app.rag.seed_postmortems import SEED_POSTMORTEMS  # noqa: E402
from sqlalchemy import insert, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_postmortems")

ROOT_CAUSE_DATABASE_URL = os.environ.get(
    "ROOT_CAUSE_DATABASE_URL",
    "postgresql+asyncpg://root-cause-writer:root-cause-writer-dev-password@localhost:5432/signalstack",
)

#: Voyage AI accounts without a billing method on file are capped at 3
#: requests/minute (not just token-rate-limited) — see the RateLimitError
#: message Voyage returns. This script makes one embed call per new/
#: unembedded postmortem, so pacing calls this far apart is what keeps a
#: fresh corpus from tripping that cap partway through, rather than
#: relying on retry-after-failure.
MIN_SECONDS_BETWEEN_EMBED_CALLS = 21


async def main() -> None:
    engine = create_async_engine(ROOT_CAUSE_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            existing_rows = (
                await conn.execute(
                    select(postmortems.c.id, postmortems.c.title, postmortems.c.embedding)
                )
            ).all()
        existing_by_title = {row.title: row for row in existing_rows}

        inserted = backfilled = skipped = 0
        for seed in SEED_POSTMORTEMS:
            existing = existing_by_title.get(seed.title)
            if existing is not None and existing.embedding is not None:
                logger.info("skipping %r — already embedded", seed.title)
                skipped += 1
                continue

            # Unconditional, even for the very first call of this process:
            # the 3 RPM cap is a rolling window, not reset per invocation,
            # so a run started shortly after a prior run (or a prior
            # rate-limit error) can still be inside that same window.
            logger.info(
                "waiting %ds before the next embed call (Voyage's no-billing rate cap)",
                MIN_SECONDS_BETWEEN_EMBED_CALLS,
            )
            await asyncio.sleep(MIN_SECONDS_BETWEEN_EMBED_CALLS)

            embedding = await embed_document(seed.body)
            embedded_at = datetime.now(UTC)

            async with engine.begin() as conn:
                if existing is None:
                    await conn.execute(
                        insert(postmortems).values(
                            id=uuid.uuid4(),
                            title=seed.title,
                            body=seed.body,
                            embedding=embedding,
                            embedded_at=embedded_at,
                        )
                    )
                    logger.info("inserted %r (%d-dim embedding)", seed.title, len(embedding))
                    inserted += 1
                else:
                    await conn.execute(
                        update(postmortems)
                        .where(postmortems.c.id == existing.id)
                        .values(embedding=embedding, embedded_at=embedded_at, embedding_error=None)
                    )
                    logger.info("backfilled embedding for %r (%d-dim)", seed.title, len(embedding))
                    backfilled += 1

        logger.info(
            "done: %d inserted, %d backfilled, %d already up to date", inserted, backfilled, skipped
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
