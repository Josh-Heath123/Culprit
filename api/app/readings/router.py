"""`POST /readings`, `GET /probes`, `POST /probes/{probe_id}/run` — Phase 31.

Mounted in app/main.py with no router-level dependency, like the other
Phase 28-30 routers and for the same reason: the write takes an agent's
signature and the two probe routes take a user session. Declared per
route, so an endpoint added here later cannot inherit a credential nobody
chose for it.

**`POST /readings` accepts an agent's credential and nothing else** (Phase
33 part 2; until then it took the project token). A reading is a
measurement of a running system, so it is written only by the agent that
took it: every reading's `agent_id` must be the signing agent's own, and a
body naming another agent is refused whole.

`POST /probes/{probe_id}/run` is the honest one. It answers 503 and does
not run anything — see `_run_probe`.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dependencies import AgentPrincipal, require_agent
from app.auth.dependencies import require_auth
from app.readings import catalogue
from app.readings.dependencies import get_probe_writer_session
from app.readings.schemas import (
    ProbeCatalogue,
    ProbeRunUnavailable,
    ReadingBatch,
    ReadingsAccepted,
)
from app.readings.service import RejectedByDatabase, store_readings

logger = structlog.get_logger("readings")

router = APIRouter(tags=["readings"])

#: The phase that gives this API a way to reach a probe agent. Named in
#: the 503 body so a caller can tell "not yet built" from "temporarily
#: down" without reading the plan.
_AGENT_TRANSPORT_PHASE = "Phase 33"


@router.post("/readings", response_model=ReadingsAccepted, status_code=201)
async def create_readings(
    payload: ReadingBatch,
    agent: AgentPrincipal = Depends(require_agent),
    session: AsyncSession = Depends(get_probe_writer_session),
) -> ReadingsAccepted:
    others = sorted({r.agent_id for r in payload.readings if r.agent_id != agent.id})
    if others:
        logger.warning("readings_refused_other_agent", agent=agent.id, named=others)
        raise HTTPException(
            status_code=403,
            detail="every reading must name the agent that signed the request",
        )
    try:
        stored = await store_readings(session, payload.readings)
    except RejectedByDatabase as exc:
        # 422 with the constraint's rule, never the row: a reading carries
        # `measured` and `evidence`, and Postgres renders the failing row
        # into its own error text.
        logger.warning("readings_rejected_by_database", constraint=exc.constraint)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("readings_stored", stored=stored.stored, duplicates=stored.duplicates)
    return ReadingsAccepted(
        stored=stored.stored,
        duplicates=stored.duplicates,
        stored_at=datetime.now(UTC),
    )


@router.get("/probes", response_model=ProbeCatalogue, dependencies=[Depends(require_auth)])
async def list_probes() -> ProbeCatalogue:
    """Every probe this build can describe.

    A mirror of the binary's catalogue, not a second implementation of it
    — see app/readings/catalogue.py for why the control plane holds
    descriptions at all when it cannot run a single one of them.
    """
    return ProbeCatalogue(probes=list(catalogue.CATALOGUE))


@router.post(
    "/probes/{probe_id}/run",
    response_model=ProbeRunUnavailable,
    status_code=503,
    dependencies=[Depends(require_auth)],
)
async def run_probe(probe_id: str) -> ProbeRunUnavailable:
    """Refuses, and says what to run instead.

    Probes execute in the `culprit` binary (Phase 31 field 3), against an
    environment the binary can reach. This API has no transport to an
    agent until Phase 33, and three ways of pretending otherwise were all
    available and all wrong: shell out to a binary that may not be
    installed and would run against the *server's* network rather than
    the target's; return an empty success; or synthesise a reading. The
    last is the one that matters — a fabricated measurement is
    indistinguishable from a real one the moment it is stored, and the
    whole OBSERVED plane is worth nothing if a row in it might be a
    guess.

    So: 404 if the id names no probe (a caller with a typo should learn
    that, not a generic outage), and otherwise 503 with the command that
    does the thing. Nothing is written either way.
    """
    manifest = catalogue.get(probe_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="no probe with that id")

    logger.info("probe_run_refused", probe_id=probe_id, reason="no agent transport")
    return ProbeRunUnavailable(
        probe_id=probe_id,
        reason=(
            "this route runs nothing. Probes run in the culprit binary, against "
            "an environment it can reach: address one to a paired agent as a task "
            "(POST /agents/{agent_id}/tasks), or run it locally."
        ),
        run_locally=f"culprit probe {probe_id} --env <environment>",
        available_from=_AGENT_TRANSPORT_PHASE,
    )
