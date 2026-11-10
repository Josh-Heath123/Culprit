"""The agent routes — Phase 33, part 2: the agent meets the control plane.

Three kinds of caller, each declared per route so a route added later
inherits no credential nobody chose for it:

- **An admin** (a user session): make a pairing code, list agents, set an
  agent's allowance, revoke it, address a task to it, read its tasks and
  audit log.
- **An agent pairing** (`POST /agents/register`): authenticated by the
  single-use code alone, and able to do nothing but spend it.
- **A paired agent** (`require_agent`, every request signed with its key):
  claim its next task, report a result, read and extend its audit chain.

No route here runs a probe. An agent runs what it claims, under its own
configuration's grants intersected with the allowance stamped on the task.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service
from app.agents.dependencies import (
    AgentPrincipal,
    body_documented_as,
    get_admin_session,
    get_gateway_session,
    get_registrar_session,
    require_agent,
    signed_body,
)
from app.agents.schemas import (
    AgentList,
    AgentRegistered,
    AgentSummary,
    Allowance,
    AllowanceChange,
    AuditEntries,
    AuditHead,
    AuditLog,
    AuditRow,
    ClaimedTask,
    PairingCodeCreated,
    RegisterAgent,
    TaskCreate,
    TaskCreated,
    TaskResult,
    TaskView,
)
from app.auth.dependencies import require_admin
from app.auth.security import AuthenticatedUser
from app.investigations import service as investigations
from app.investigations.dependencies import get_read_session

logger = structlog.get_logger("agents")
router = APIRouter(prefix="/agents", tags=["agents"])

#: The bodies of an agent's own requests, parsed once its signature holds.
_task_result = signed_body(TaskResult)
_audit_entries = signed_body(AuditEntries)

#: Ids a route under /agents/me would shadow.
_RESERVED_IDS = {"me", "register", "pairing-codes"}


# ---- a paired agent's own routes (declared first: /agents/me/...) -------------------


@router.post("/me/tasks/claim", response_model=ClaimedTask, responses={204: {}})
async def claim_task(
    agent: AgentPrincipal = Depends(require_agent),
    session: AsyncSession = Depends(get_gateway_session),
) -> ClaimedTask | Response:
    task = await service.claim(session, agent.id)
    if task is None:
        return Response(status_code=204)
    logger.info("agent_task_claimed", agent=agent.id, task=task["id"])
    return ClaimedTask(**task)


@router.post(
    "/me/tasks/{task_id}/result", status_code=204, openapi_extra=body_documented_as(TaskResult)
)
async def report_result(
    task_id: str,
    result: TaskResult = Depends(_task_result),
    agent: AgentPrincipal = Depends(require_agent),
    session: AsyncSession = Depends(get_gateway_session),
) -> Response:
    try:
        await service.complete(session, agent.id, task_id, result)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail="no claimed, open task with that id") from exc
    logger.info("agent_task_completed", agent=agent.id, task=task_id, outcome=result.outcome)
    return Response(status_code=204)


@router.get("/me/audit/head", response_model=AuditHead)
async def audit_head(
    agent: AgentPrincipal = Depends(require_agent),
    session: AsyncSession = Depends(get_gateway_session),
) -> AuditHead:
    seq, digest = await service.audit_head(session, agent.id)
    return AuditHead(seq=seq, hash=digest)


@router.post("/me/audit", response_model=AuditHead, openapi_extra=body_documented_as(AuditEntries))
async def append_audit(
    body: AuditEntries = Depends(_audit_entries),
    agent: AgentPrincipal = Depends(require_agent),
    session: AsyncSession = Depends(get_gateway_session),
) -> AuditHead:
    try:
        seq, digest = await service.append_audit(session, agent.id, body.entries)
    except service.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.ChainBroken as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "seq": exc.head[0], "hash": exc.head[1]},
        ) from exc
    return AuditHead(seq=seq, hash=digest)


# ---- pairing ---------------------------------------------------------------------------


@router.post("/pairing-codes", response_model=PairingCodeCreated, status_code=201)
async def create_pairing_code(
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_admin_session),
) -> PairingCodeCreated:
    code, expires_at = await service.create_pairing_code(session, user.username)
    logger.info("agent_pairing_code_created", by=user.username)
    return PairingCodeCreated(code=code, expires_at=expires_at)


@router.post("/register", response_model=AgentRegistered, status_code=201)
async def register(
    body: RegisterAgent, session: AsyncSession = Depends(get_registrar_session)
) -> AgentRegistered:
    if body.agent_id in _RESERVED_IDS:
        raise HTTPException(status_code=422, detail=f"{body.agent_id!r} is reserved")
    try:
        agent_id = await service.register(session, body)
    except service.Refused as exc:
        status = 409 if "already paired" in str(exc) else 401
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    logger.info("agent_registered", agent=agent_id)
    return AgentRegistered(agent_id=agent_id)


# ---- an admin's view and controls -----------------------------------------------------


@router.get("", response_model=AgentList, dependencies=[Depends(require_admin)])
async def list_agents(session: AsyncSession = Depends(get_read_session)) -> AgentList:
    return AgentList(items=[AgentSummary(**row) for row in await service.list_agents(session)])


@router.patch("/{agent_id}/grants", response_model=Allowance)
async def set_allowance(
    agent_id: str,
    body: AllowanceChange,
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_admin_session),
) -> Allowance:
    try:
        grants = await service.set_allowance(
            session, agent_id, body.environment, body.grants, user.username
        )
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail="no such agent") from exc
    except service.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info(
        "agent_allowance_set", agent=agent_id, environment=body.environment, by=user.username
    )
    return Allowance(agent_id=agent_id, environment=body.environment, grants=grants)


@router.post("/{agent_id}/revoke", status_code=204)
async def revoke(
    agent_id: str,
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_admin_session),
) -> Response:
    try:
        await service.revoke(session, agent_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail="no such agent") from exc
    logger.info("agent_revoked", agent=agent_id, by=user.username)
    return Response(status_code=204)


@router.post("/{agent_id}/tasks", response_model=TaskCreated, status_code=201)
async def create_task(
    agent_id: str,
    body: TaskCreate,
    user: AuthenticatedUser = Depends(require_admin),
    session: AsyncSession = Depends(get_admin_session),
    reader: AsyncSession = Depends(get_read_session),
) -> TaskCreated:
    if body.verify is not None:
        # A verify task names an investigation that exists, in the
        # environment the task runs in. Whether the agent diagnosed it is
        # the agent's to say: one that did not holds no record of before,
        # and answers inconclusive, saying so.
        investigation = await investigations.load(reader, body.verify.investigation_id)
        if investigation is None:
            raise HTTPException(status_code=404, detail="no such investigation")
        if investigation.environment != body.environment:
            raise HTTPException(
                status_code=422,
                detail=f"{investigation.id} is an investigation of {investigation.environment}, "
                f"not {body.environment}",
            )
    try:
        task_id = await service.create_task(session, agent_id, body, user.username)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail="no such agent") from exc
    except service.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("agent_task_created", agent=agent_id, task=task_id, by=user.username)
    return TaskCreated(id=task_id)


@router.get(
    "/{agent_id}/tasks/{task_id}", response_model=TaskView, dependencies=[Depends(require_admin)]
)
async def get_task(
    agent_id: str, task_id: str, session: AsyncSession = Depends(get_read_session)
) -> TaskView:
    try:
        return TaskView(**await service.load_task(session, agent_id, task_id))
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail="no such task") from exc


@router.get("/{agent_id}/audit", response_model=AuditLog, dependencies=[Depends(require_admin)])
async def get_audit(agent_id: str, session: AsyncSession = Depends(get_read_session)) -> AuditLog:
    rows = await service.read_audit(session, agent_id)
    return AuditLog(
        agent_id=agent_id,
        items=[AuditRow(**{key: row[key] for key in AuditRow.model_fields}) for row in rows],
    )
