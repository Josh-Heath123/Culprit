"""The narration job — Phase 35 part 2.

Every tick, the newest investigations that have no complete narration and
fewer than three attempts are narrated, a few at a time. Each attempt is
one call to the provider, with the investigation's numbered evidence and
nothing else, and ends in exactly one row with its final status:

- `complete` — the reply passed `culprit_model.narration.check`;
- `refused`  — it named something the investigation does not hold; what it
  named is stored, the prose is not;
- `failed`   — the provider erred, timed out or answered empty, with a
  reason built from closed vocabulary and redacted.

No row is written before the attempt ends, so nothing is ever pending. A
fourth attempt is never made: the job does not pick an investigation with
three, and the database refuses a fourth (`ck_narrations_three_attempts`).
A failed or refused attempt is retried no sooner than RETRY_AFTER later.

The job reads the investigation tables and its own narrations, and inserts
narrations, as the `narrator` role — and does nothing else.
"""

import asyncio
import logging
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from culprit_model.investigations import Investigation, from_rows
from culprit_model.narration import MAX_PROSE, check, evidence
from culprit_model.redaction import redact_credentials
from sqlalchemy import Table, and_, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.narrate import prompts, tables
from app.narrate.providers import Provider, ProviderError
from app.observability import instrument_job

logger = logging.getLogger("narrate.job")

MAX_ATTEMPTS = 3
#: Investigations narrated per tick.
BATCH = 3
#: How long after a failed or refused attempt the next one may be made,
#: unless NARRATOR_RETRY_SECONDS says otherwise (app/narrate/config.py).
RETRY_AFTER = timedelta(seconds=60)
#: Bounds on what is stored about an attempt (the migration's CHECKs).
MAX_REASON = 500
MAX_NAMED = 20
MAX_NAMED_LENGTH = 200


def _id() -> str:
    return "nar-" + secrets.token_hex(8)


async def due(conn: AsyncConnection, retry_after: timedelta = RETRY_AFTER) -> list[str]:
    """The investigations to narrate now, newest first: none attempted, or
    fewer than three attempts, none complete, the last one long enough ago."""
    n = tables.narrations
    attempts = (
        select(
            n.c.investigation_id,
            func.count().label("attempts"),
            func.bool_or(n.c.status == "complete").label("done"),
            func.max(n.c.narrated_at).label("last"),
        )
        .group_by(n.c.investigation_id)
        .subquery()
    )
    i = tables.investigations
    query = (
        select(i.c.id)
        .select_from(i.outerjoin(attempts, attempts.c.investigation_id == i.c.id))
        .where(
            or_(
                attempts.c.attempts.is_(None),
                and_(
                    attempts.c.attempts < MAX_ATTEMPTS,
                    ~attempts.c.done,
                    attempts.c.last <= func.now() - retry_after,
                ),
            )
        )
        .order_by(i.c.ingested_at.desc())
        .limit(BATCH)
    )
    return list((await conn.execute(query)).scalars())


async def load(conn: AsyncConnection, investigation_id: str) -> Investigation | None:
    """The investigation as the API rebuilds it — the same `from_rows` — so
    the evidence numbers the narrator cites are the ones the API checks."""
    row = (
        (
            await conn.execute(
                select(tables.investigations).where(tables.investigations.c.id == investigation_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None

    async def rows(table: Table) -> Sequence[Mapping[Any, Any]]:
        query = select(table).where(table.c.investigation_id == investigation_id)
        return list((await conn.execute(query)).mappings().all())

    return from_rows(
        row,
        await rows(tables.investigation_readings),
        await rows(tables.hypotheses),
        await rows(tables.fault_edges),
        await rows(tables.fault_edge_readings),
    )


async def _attempts(conn: AsyncConnection, investigation_id: str) -> tuple[int, bool]:
    n = tables.narrations
    count, done = (
        await conn.execute(
            select(func.count(), func.coalesce(func.bool_or(n.c.status == "complete"), False))
            .select_from(n)
            .where(n.c.investigation_id == investigation_id)
        )
    ).one()
    return int(count), bool(done)


def _constraint(exc: IntegrityError) -> str:
    """The violated constraint's name, never the error's text: Postgres
    renders the failing row into it."""
    orig = getattr(exc, "orig", None)
    driver = getattr(orig, "__cause__", None) or orig
    return str(getattr(driver, "constraint_name", "") or "")


def _reason(text: str) -> str:
    return redact_credentials(text)[:MAX_REASON] or "no reason"


async def attempt(
    provider: Provider, investigation: Investigation, timeout_seconds: float
) -> dict[str, Any]:
    """One attempt: one call, then the check. Returns the row's status
    columns. Never raises for anything the provider does."""
    user = prompts.render(evidence(investigation))
    try:
        reply = await asyncio.wait_for(
            provider.complete(prompts.SYSTEM, user), timeout=timeout_seconds
        )
    except ProviderError as exc:
        return {"status": "failed", "reason": _reason(exc.reason)}
    except TimeoutError:
        return {"status": "failed", "reason": f"{provider.name} did not answer in time"}
    except Exception as exc:
        # The exception's class, never its text: that is the provider's.
        return {"status": "failed", "reason": f"{provider.name} failed ({type(exc).__name__})"}
    prose = (reply or "").strip()
    if not prose:
        return {"status": "failed", "reason": f"{provider.name} answered with nothing"}
    if len(prose) > MAX_PROSE:
        return {
            "status": "failed",
            "reason": f"the reply from {provider.name} was longer than {MAX_PROSE} characters",
        }
    result = check(investigation, prose)
    if not result.passed:
        named = [redact_credentials(name)[:MAX_NAMED_LENGTH] for name in result.named]
        return {"status": "refused", "named": named[:MAX_NAMED]}
    return {"status": "complete", "prose": prose}


async def narrate_one(
    engine: AsyncEngine, provider: Provider, investigation_id: str, timeout_seconds: float
) -> str | None:
    """Narrate one investigation once, if it is still due. Returns the
    status written, or None when nothing was attempted."""
    async with engine.connect() as conn:
        count, done = await _attempts(conn, investigation_id)
        if done or count >= MAX_ATTEMPTS:
            return None
        investigation = await load(conn, investigation_id)
    if investigation is None:
        return None
    outcome = await attempt(provider, investigation, timeout_seconds)
    row: dict[str, Any] = {
        "id": _id(),
        "investigation_id": investigation_id,
        "attempt": count + 1,
        "provider": provider.name,
        "model": provider.model[:200],
        "prose": None,
        "reason": None,
        "named": None,
        "narrated_at": datetime.now(UTC),
        **outcome,
    }
    try:
        async with engine.begin() as conn:
            await conn.execute(insert(tables.narrations).values(**row))
    except IntegrityError as exc:
        if _constraint(exc) != "uq_narrations_attempt":
            raise
        # Another worker wrote this attempt first; its row stands.
        logger.info("narration_attempt_taken investigation=%s", investigation_id)
        return None
    # Never the prose, and the reason is closed vocabulary, redacted.
    logger.info(
        "narration status=%s investigation=%s attempt=%d provider=%s",
        row["status"],
        investigation_id,
        row["attempt"],
        provider.name,
    )
    return str(row["status"])


@instrument_job("narrate_investigations")
async def narrate_investigations(ctx: dict) -> dict[str, int]:
    """The cron job. With LLM_PROVIDER=none there is no provider and it
    returns at once: nothing is read, nothing is called."""
    provider: Provider | None = ctx.get("narrator_provider")
    if provider is None:
        return {"narrated": 0}
    engine: AsyncEngine = ctx["narrator_engine"]
    config = ctx["narrator_config"]
    timeout = float(config.timeout_seconds)
    async with engine.connect() as conn:
        investigation_ids = await due(conn, timedelta(seconds=config.retry_seconds))
    narrated = 0
    for investigation_id in investigation_ids:
        if await narrate_one(engine, provider, investigation_id, timeout) is not None:
            narrated += 1
    return {"narrated": narrated}
