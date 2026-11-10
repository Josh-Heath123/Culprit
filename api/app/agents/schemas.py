"""Request and response bodies for the agent routes (Phase 33 part 2)."""

import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from culprit_model.capabilities import Capability
from culprit_model.subjects import SubjectError, build
from culprit_model.verifications import Change, ChangeKind
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.signing import AGENT_ID


def _grant_names(names: list[str]) -> list[str]:
    """A grant list as an operator or an agent may write it: names from
    the closed vocabulary, exactly — never a wildcard, `all` or a write."""
    seen: list[str] = []
    for name in names:
        if "*" in name or name.strip().lower() == "all":
            raise ValueError(f"{name!r}: name each grant exactly; wildcards and `all` are refused")
        try:
            Capability(name)
        except ValueError:
            raise ValueError(f"{name!r} is not a capability (docs/PERMISSIONS.md)") from None
        if name not in seen:
            seen.append(name)
    return sorted(seen)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairingCodeCreated(BaseModel):
    code: str
    expires_at: datetime


class RegisterAgent(_Strict):
    pairing_code: str = Field(min_length=8, max_length=128)
    agent_id: str
    #: The Ed25519 public key, base64 of its 32 bytes. Never the private half.
    public_key: str
    #: What the agent's own configuration grants, per environment: what an
    #: operator may later allow, and never more.
    grants: dict[str, list[str]]

    @field_validator("agent_id")
    @classmethod
    def _agent_id(cls, value: str) -> str:
        if not AGENT_ID.match(value):
            raise ValueError("agent_id must be 1-64 letters, digits, '.', '_' or '-'")
        return value

    @field_validator("public_key")
    @classmethod
    def _key(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("public_key must be base64") from None
        if len(raw) != 32:
            raise ValueError("public_key must be a 32-byte Ed25519 public key")
        return value

    @field_validator("grants")
    @classmethod
    def _grants(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return {environment: _grant_names(names) for environment, names in value.items()}


class AgentRegistered(BaseModel):
    agent_id: str


class AgentSummary(BaseModel):
    id: str
    registered_at: datetime
    revoked_at: datetime | None
    reported_grants: dict[str, list[str]]
    allowances: dict[str, list[str]]
    #: When the agent last made a request its signature authenticated. None
    #: until it makes one. A refused request is never stored, so it never
    #: moves this.
    last_request_at: datetime | None = None


class AgentList(BaseModel):
    items: list[AgentSummary]


class AllowanceChange(_Strict):
    environment: str = Field(min_length=1, max_length=128)
    grants: list[str]

    @field_validator("grants")
    @classmethod
    def _grants(cls, value: list[str]) -> list[str]:
        return _grant_names(value)


class Allowance(BaseModel):
    agent_id: str
    environment: str
    grants: list[str]


class ProbeSpec(_Strict):
    probe_id: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=1024)
    inputs: dict[str, Any] | None = None


class DiagnoseSpec(_Strict):
    symptom: str = Field(min_length=1, max_length=1024)
    from_: str | None = Field(default=None, alias="from")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class VerifySpec(_Strict):
    """`culprit verify` as a task (Phase 34 part 2): measure again what an
    investigation this agent diagnosed found, after a change was applied."""

    investigation_id: str = Field(pattern=r"^inv-[0-9a-f]{16}$")
    #: What was applied. Each is a change, or the words `culprit verify
    #: --change` takes — `config:<component>/<key>`, `image:<component>`,
    #: `commit:<sha>`, `action:<what was done>` — read into one here, with
    #: its subject built by `subjects.build()` (the dashboard formats no
    #: subject). None named is allowed and verifies as inconclusive.
    #: (Typed `Change | str` so the schema says both are accepted; every
    #: string is read into a Change before the field is validated.)
    changes: list[Change | str] = Field(default_factory=list, max_length=32)

    @field_validator("changes", mode="before")
    @classmethod
    def _read_change_words(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [parse_change(item) if isinstance(item, str) else item for item in value]
    #: Whether the fault was planted (a drill) or happened on a real
    #: system: said by whoever asks, never guessed.
    source: Literal["planted", "real"]


def parse_change(words: str) -> Change:
    """`--change` words into a change: the Python half of the binary's
    parseChanges (cli/cmd/culprit/verify.go), subjects built, never
    formatted."""
    kind, found, rest = words.partition(":")
    if not found:
        raise ValueError(
            f"{words!r}: want config:<component>/<key>, image:<component>, commit:<sha> "
            "or action:<what was done>"
        )
    try:
        if kind == "config":
            component, slash, key = rest.partition("/")
            if not slash:
                raise ValueError(f"{words!r}: want config:<component>/<key>")
            return Change(
                kind=ChangeKind.CONFIG, subject=build("config", component=component, key=key)
            )
        if kind == "image":
            return Change(kind=ChangeKind.IMAGE, subject=build("image", component=rest))
        if kind == "commit":
            return Change(kind=ChangeKind.COMMIT, ref=rest.strip().lower())
        if kind == "action":
            return Change(kind=ChangeKind.ACTION, description=rest.strip())
    except SubjectError as exc:
        raise ValueError(f"{words!r}: {exc}") from None
    raise ValueError(f"{words!r}: {kind!r} is not config, image, commit or action")


class TaskCreate(_Strict):
    environment: str = Field(min_length=1, max_length=128)
    kind: Literal["probe", "diagnose", "verify"]
    probe: ProbeSpec | None = None
    diagnose: DiagnoseSpec | None = None
    verify: VerifySpec | None = None


class TaskCreated(BaseModel):
    id: str


class ClaimedTask(BaseModel):
    """What an agent receives: the shape of `agent.Task` in the binary."""

    id: str
    environment: str
    kind: str
    probe: dict[str, Any] | None = None
    diagnose: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    #: The operator's allowance for this environment, as it stood when the
    #: task was claimed. The agent intersects it with its own grants.
    allowance: list[str]


class TaskResult(_Strict):
    outcome: Literal["completed", "refused", "error"]
    reason: str | None = Field(default=None, max_length=4096)
    grants_held: list[str] = []
    allowance_ignored: list[str] = []
    readings: int = 0
    investigation_id: str | None = Field(default=None, max_length=128)
    #: A verify task's verification, once stored, and its verdict — or the
    #: verdict alone, `inconclusive`, when nothing could be measured.
    verification_id: str | None = Field(default=None, max_length=128)
    verdict: (
        Literal["verified", "not_resolved", "regressed", "changed_underneath", "inconclusive"]
        | None
    ) = None


class TaskView(BaseModel):
    id: str
    agent_id: str
    environment: str
    kind: str
    spec: dict[str, Any]
    created_by: str
    created_at: datetime
    claimed_at: datetime | None
    allowance: list[str] | None
    completed_at: datetime | None
    outcome: str | None
    reason: str | None
    result: dict[str, Any] | None
    investigation_id: str | None


class AuditEntries(_Strict):
    #: Each entry exactly as the agent's log holds it: one JSON line.
    entries: list[str] = Field(min_length=1, max_length=1000)


class AuditHead(BaseModel):
    seq: int
    hash: str


class AuditRow(BaseModel):
    seq: int
    kind: str
    task_id: str
    probe_id: str | None
    target: str | None
    verdict: str | None
    grants: list[str]
    hash: str
    prev: str
    received_at: datetime


class AuditLog(BaseModel):
    agent_id: str
    items: list[AuditRow]
