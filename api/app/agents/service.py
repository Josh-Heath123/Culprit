"""Pairing, allowances, tasks and the audit log (Phase 33 part 2).

Each function takes the session of the one role its statements need
(migrations/versions/d7a3e5f1b9c2_agents.py): pairing codes, allowances,
revocation and new tasks as `agent-admin`; registration as
`agent-registrar`; claims, results and audit entries as `agent-gateway`;
reads as `api-reader`.
"""

import base64
import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import tables
from app.agents.schemas import RegisterAgent, TaskCreate, TaskResult

#: A pairing code is good for this long, and once (the plan's default).
PAIRING_CODE_LIFETIME = timedelta(minutes=15)
GENESIS = "0" * 64

_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L, U


class NotFound(Exception):
    pass


class Refused(Exception):
    """A request the caller may not make. The message is safe to return."""


class ChainBroken(Exception):
    def __init__(self, message: str, head: tuple[int, str]):
        super().__init__(message)
        self.head = head


def _now() -> datetime:
    return datetime.now(UTC)


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


# ---- pairing ------------------------------------------------------------------


async def create_pairing_code(session: AsyncSession, created_by: str) -> tuple[str, datetime]:
    """A fresh code: about 118 bits, in groups a person can copy. Only its
    hash is stored; the code itself is returned once."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(24))
    code = "-".join(raw[index : index + 6] for index in range(0, 24, 6))
    expires_at = _now() + PAIRING_CODE_LIFETIME
    await session.execute(
        insert(tables.agent_pairing_codes).values(
            code_hash=code_hash(code),
            created_by=created_by,
            created_at=_now(),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return code, expires_at


async def register(session: AsyncSession, body: RegisterAgent) -> str:
    """Spend the code and record the agent, in one transaction: a code
    that is unknown, used or expired registers nothing, and a refused
    registration (an id or key already paired) leaves the code unspent."""
    spent = (
        await session.execute(
            update(tables.agent_pairing_codes)
            .where(
                and_(
                    tables.agent_pairing_codes.c.code_hash == code_hash(body.pairing_code),
                    tables.agent_pairing_codes.c.used_at.is_(None),
                    tables.agent_pairing_codes.c.expires_at > func.now(),
                )
            )
            .values(used_at=func.now(), used_by=body.agent_id)
            .returning(tables.agent_pairing_codes.c.id)
        )
    ).first()
    if spent is None:
        await session.rollback()
        raise Refused("the pairing code is not valid")
    try:
        await session.execute(
            insert(tables.agents).values(
                id=body.agent_id,
                public_key=base64.b64decode(body.public_key),
                reported_grants=body.grants,
                registered_at=_now(),
                pairing_code_id=spent.id,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise Refused("an agent with that id or key is already paired") from None
    return body.agent_id


# ---- what an admin sees and does --------------------------------------------------


async def list_agents(session: AsyncSession) -> list[dict[str, Any]]:
    agents = (await session.execute(select(tables.agents).order_by(tables.agents.c.id))).all()
    allowances = (await session.execute(select(tables.agent_allowances))).all()
    # When each agent last made a signed request: the newest nonce it spent,
    # which the gateway's cleanup always keeps (app/agents/dependencies.py).
    nonces = tables.agent_nonces
    newest = await session.execute(
        select(nonces.c.agent_id, func.max(nonces.c.seen_at)).group_by(nonces.c.agent_id)
    )
    last_request = {row[0]: row[1] for row in newest.all()}
    by_agent: dict[str, dict[str, list[str]]] = {}
    for row in allowances:
        by_agent.setdefault(row.agent_id, {})[row.environment] = list(row.grants)
    return [
        {
            "id": agent.id,
            "registered_at": agent.registered_at,
            "revoked_at": agent.revoked_at,
            "reported_grants": agent.reported_grants,
            "allowances": by_agent.get(agent.id, {}),
            "last_request_at": last_request.get(agent.id),
        }
        for agent in agents
    ]


async def set_allowance(
    session: AsyncSession, agent_id: str, environment: str, grants: list[str], updated_by: str
) -> list[str]:
    """The operator's allowance for one environment — only ever inside what
    the agent reports holding there. It can withhold; it cannot add."""
    agent = (
        await session.execute(
            select(tables.agents.c.reported_grants, tables.agents.c.revoked_at).where(
                tables.agents.c.id == agent_id
            )
        )
    ).first()
    if agent is None:
        raise NotFound
    reported = set(agent.reported_grants.get(environment, []))
    beyond = sorted(set(grants) - reported)
    if beyond:
        raise Refused(
            f"the agent does not report holding {', '.join(beyond)} in {environment!r}; "
            "an allowance can only narrow what an agent holds"
        )
    await session.execute(
        pg_insert(tables.agent_allowances)
        .values(
            agent_id=agent_id,
            environment=environment,
            grants=grants,
            updated_by=updated_by,
            updated_at=_now(),
        )
        .on_conflict_do_update(
            index_elements=["agent_id", "environment"],
            set_={"grants": grants, "updated_by": updated_by, "updated_at": _now()},
        )
    )
    await session.commit()
    return grants


async def revoke(session: AsyncSession, agent_id: str) -> None:
    changed = (
        await session.execute(
            update(tables.agents)
            .where(tables.agents.c.id == agent_id)
            .values(revoked_at=func.coalesce(tables.agents.c.revoked_at, func.now()))
            .returning(tables.agents.c.id)
        )
    ).first()
    if changed is None:
        await session.rollback()
        raise NotFound
    await session.commit()


async def create_task(
    session: AsyncSession, agent_id: str, body: TaskCreate, created_by: str
) -> str:
    agent = (
        await session.execute(
            select(tables.agents.c.revoked_at).where(tables.agents.c.id == agent_id)
        )
    ).first()
    if agent is None:
        raise NotFound
    if agent.revoked_at is not None:
        raise Refused("the agent is revoked")
    given = {
        name
        for name, value in (
            ("probe", body.probe),
            ("diagnose", body.diagnose),
            ("verify", body.verify),
        )
        if value is not None
    }
    if given != {body.kind}:
        raise Refused(f"a {body.kind} task needs {body.kind}, and nothing else")
    spec: dict[str, Any]
    if body.probe is not None:
        spec = {"probe": body.probe.model_dump(exclude_none=True)}
    elif body.diagnose is not None:
        spec = {"diagnose": body.diagnose.model_dump(by_alias=True, exclude_none=True)}
    else:
        assert body.verify is not None
        spec = {"verify": body.verify.model_dump(mode="json", exclude_none=True)}
    task_id = "task-" + secrets.token_hex(8)
    await session.execute(
        insert(tables.agent_tasks).values(
            id=task_id,
            agent_id=agent_id,
            environment=body.environment,
            kind=body.kind,
            spec=spec,
            created_by=created_by,
            created_at=_now(),
        )
    )
    await session.commit()
    return task_id


async def load_task(session: AsyncSession, agent_id: str, task_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            select(tables.agent_tasks).where(
                and_(tables.agent_tasks.c.id == task_id, tables.agent_tasks.c.agent_id == agent_id)
            )
        )
    ).first()
    if row is None:
        raise NotFound
    return dict(row._mapping)


# ---- what an agent does -------------------------------------------------------------


async def claim(session: AsyncSession, agent_id: str) -> dict[str, Any] | None:
    """The agent's oldest unclaimed task, claimed atomically — two claims
    never get one task, and an agent can claim only its own. The allowance
    is stamped as it stands now, so a grant removed from it takes effect on
    the next task claimed."""
    row = (
        await session.execute(
            text(
                """
                UPDATE agent_tasks t SET
                    claimed_at = now(),
                    allowance = coalesce(
                        (SELECT a.grants FROM agent_allowances a
                         WHERE a.agent_id = t.agent_id AND a.environment = t.environment),
                        '{}'::text[])
                WHERE t.id = (
                    SELECT id FROM agent_tasks
                    WHERE agent_id = :agent_id AND claimed_at IS NULL
                    ORDER BY created_at, id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED)
                RETURNING t.id, t.environment, t.kind, t.spec, t.allowance
                """
            ),
            {"agent_id": agent_id},
        )
    ).first()
    await session.commit()
    if row is None:
        return None
    task: dict[str, Any] = {
        "id": row.id,
        "environment": row.environment,
        "kind": row.kind,
        "allowance": list(row.allowance or []),
    }
    task.update(row.spec)
    return task


async def complete(session: AsyncSession, agent_id: str, task_id: str, result: TaskResult) -> None:
    done = (
        await session.execute(
            update(tables.agent_tasks)
            .where(
                and_(
                    tables.agent_tasks.c.id == task_id,
                    tables.agent_tasks.c.agent_id == agent_id,
                    tables.agent_tasks.c.claimed_at.is_not(None),
                    tables.agent_tasks.c.completed_at.is_(None),
                )
            )
            .values(
                completed_at=func.now(),
                outcome=result.outcome,
                reason=result.reason,
                result=result.model_dump(mode="json"),
                investigation_id=result.investigation_id,
            )
            .returning(tables.agent_tasks.c.id)
        )
    ).first()
    if done is None:
        await session.rollback()
        raise NotFound
    await session.commit()


# ---- the audit log --------------------------------------------------------------------

_HASH = re.compile(r"^[0-9a-f]{64}$")


async def audit_head(session: AsyncSession, agent_id: str) -> tuple[int, str]:
    row = (
        await session.execute(
            select(tables.agent_audit_log.c.seq, tables.agent_audit_log.c.hash)
            .where(tables.agent_audit_log.c.agent_id == agent_id)
            .order_by(tables.agent_audit_log.c.seq.desc())
            .limit(1)
        )
    ).first()
    return (row.seq, row.hash) if row else (0, GENESIS)


def _checked(line: str, agent_id: str) -> dict[str, Any]:
    """One audit line, verified on its own: the agent's, well formed, and
    its hash the SHA-256 of its predecessor's hash, a newline and the line
    with its own hash emptied — exactly what the binary computed, over the
    exact bytes it wrote, so nothing has to be re-encoded to check it."""
    try:
        entry = json.loads(line)
    except ValueError:
        raise Refused("an audit entry is not JSON") from None
    if not isinstance(entry, dict):
        raise Refused("an audit entry is not an object")
    if entry.get("agent_id") != agent_id:
        raise Refused("an audit entry names another agent")
    digest, prev = entry.get("hash", ""), entry.get("prev", "")
    if not (
        isinstance(digest, str)
        and _HASH.match(digest)
        and isinstance(prev, str)
        and _HASH.match(prev)
    ):
        raise Refused("an audit entry's hash or prev is malformed")
    marker = f'"hash":"{digest}"'
    if line.count(marker) != 1 or not line.rstrip().endswith(marker + "}"):
        raise Refused("an audit entry is not as the agent wrote it")
    body = line.rstrip()[: -len(marker) - 1] + '"hash":""}'
    if hashlib.sha256((prev + "\n" + body).encode("utf-8")).hexdigest() != digest:
        raise Refused("an audit entry's content does not match its hash")
    if entry.get("kind") not in ("task", "probe") or not isinstance(entry.get("seq"), int):
        raise Refused("an audit entry's kind or seq is malformed")
    return entry


async def append_audit(session: AsyncSession, agent_id: str, lines: list[str]) -> tuple[int, str]:
    """Append entries that extend this agent's stored chain, in order, all
    or none. The database's own trigger refuses anything else as well."""
    head = await audit_head(session, agent_id)
    seq, last = head
    rows = []
    for line in lines:
        entry = _checked(line, agent_id)
        if entry["seq"] != seq + 1 or entry["prev"] != last:
            await session.rollback()
            raise ChainBroken("the entries do not extend the stored chain", head)
        grants = entry.get("grants") or []
        rows.append(
            {
                "agent_id": agent_id,
                "seq": entry["seq"],
                "prev": entry["prev"],
                "hash": entry["hash"],
                "kind": entry["kind"],
                "task_id": str(entry.get("task_id", "")),
                "probe_id": entry.get("probe_id") or None,
                "target": entry.get("target") or None,
                "verdict": entry.get("verdict") or None,
                "grants": [str(grant) for grant in grants],
                "entry": line.rstrip(),
                "received_at": _now(),
            }
        )
        seq, last = entry["seq"], entry["hash"]
    try:
        for row in rows:
            await session.execute(insert(tables.agent_audit_log).values(**row))
        await session.commit()
    except (IntegrityError, DBAPIError) as exc:
        await session.rollback()
        # A duplicate seq (another request got there first) or the chain
        # trigger's check_violation is a chain that moved; anything else —
        # a lost connection, say — is an error, not a verdict on the chain.
        state = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if isinstance(exc, IntegrityError) or state == "23514":
            raise ChainBroken("the entries do not extend the stored chain", head) from None
        raise
    return seq, last


async def read_audit(session: AsyncSession, agent_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(tables.agent_audit_log)
            .where(tables.agent_audit_log.c.agent_id == agent_id)
            .order_by(tables.agent_audit_log.c.seq)
        )
    ).all()
    return [dict(row._mapping) for row in rows]
