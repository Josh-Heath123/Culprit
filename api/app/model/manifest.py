"""`culprit.yaml` — the declarative, committed description of a system.

docs/DIAGNOSTIC_PLAN.md Phase 27, fields 4 and 10. The point of this file
existing at all is that the system model must be reproducible from a
repository rather than clicked into a UI: reviewed like code, diffed like
code, and identical on every machine that checks the repo out.

    # culprit.yaml
    version: 1
    components:
      - name: orders-svc
        kind: service
        display_name: Orders Service
        environments: [staging, production]
        labels: {team: payments}
        monitored_metrics: []
        connections:
          - to: payments-svc
            kind: http
            criticality: on_request_path
          - to: orders-db
            kind: sql
      - name: orders-db
        kind: database

**Connections are nested under their source component, not listed
separately.** A connection has no identity apart from the pair it joins,
and the flat form makes it possible to declare an edge whose endpoints
are not in the file — a hole in the model that reads as an edge. Nesting
makes the source endpoint structurally present; `_check_targets_exist`
covers the other end.

**No values, ever (field 12).** `culprit.yaml` names config keys; it
never carries their values. `_reject_credentials` refuses anything that
looks like one before the file reaches the database, because a manifest
is a committed file and a credential committed once is a credential
leaked permanently. The check is deliberately a blunt refusal rather than
a redaction: silently stripping a secret would leave the author believing
the file said something it does not.

Loading is pure — `load_manifest` parses a string. The only I/O is
`read_manifest`, which is a one-line convenience for the CLI entry point.
"""

import datetime
import functools
import math
import re
import types
import typing
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import yaml
from culprit_model import subjects
from culprit_model.capabilities import ALLOWLISTED, Capability
from culprit_model.graph import (
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    Criticality,
    DeclaredBy,
    SystemGraph,
)
from culprit_model.latency import (
    BUDGET_MERGE_PROBLEM,
    STATEMENT_BUDGET_PREDICATES,
    Budget,
    budget_literal_problem,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

#: The one shape this loader understands. An explicit version so a later
#: phase can change the schema without having to guess what an
#: unversioned file meant.
MANIFEST_VERSION = 1

#: Must match the OTel `service.name` resource attribute byte-for-byte —
#: the same pattern api/app/model/schemas.py enforces on the HTTP path,
#: because a component created through the manifest and one created
#: through the API have to be the same kind of thing.
COMPONENT_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,62}$"


class ManifestError(ValueError):
    """Raised for a manifest that cannot be loaded.

    Loud, and carrying the offending path, for the same reason
    `subjects.SubjectError` is: a manifest that half-loads produces a
    partial system model, and a partial model produces confident findings
    about a system that is not the one described.
    """


#: Keys whose *presence with a value* in a manifest means a secret has
#: been committed. Matched case-insensitively against the whole key.
_SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|credential|auth[_-]?token|session[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)

#: Values that are self-evidently credentials whatever they are called —
#: a DSN with inline auth, a bearer token, a PEM block, an AWS key id.
#: Checked in addition to the key name, because `labels: {note: "use
#: postgres://u:p@host/db"}` is just as leaked as `password: p`.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),  # user:pass@host
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
)


#: The one place a key named like a credential is not one: an environment's
#: `components.<name>.tokens`, which maps a callee to the *name* of the
#: variable holding the token (Phase 32; cli/internal/extract/
#: environments.go `ComponentSettings.Tokens`). The same name rule as Go's
#: `envVarName`. Matched on the exact path, so a dotted name — which this
#: split cannot place — falls through to the ordinary refusal.
_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_token_reference_map(path: str, key: object) -> bool:
    parts = path.split(".")
    return (
        key == "tokens"
        and len(parts) == 4
        and parts[0] == "environments"
        and parts[2] == "components"
    )


def _reject_credentials(node: Any, path: str = "") -> None:
    """Walks a parsed manifest and refuses anything credential-shaped.

    Phase 27 field 12: "`culprit.yaml` contains no secrets by
    construction — it names config keys, never values, and the loader
    rejects any value that looks like a credential."

    The error message never echoes the offending value. A loader that
    prints the secret it just refused has leaked it into a terminal
    scrollback and a CI log, which is most of the damage it was trying to
    prevent.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if _is_token_reference_map(path, key):
                if not isinstance(value, dict) or not all(
                    isinstance(v, str) and _ENV_VAR_NAME.match(v) for v in value.values()
                ):
                    # Never echoed: if it is not a variable name, the
                    # likeliest thing it is is the token.
                    raise ManifestError(
                        f"{here}: each value must be the *name* of an environment "
                        "variable holding the token, never the token."
                    )
                # A name-shaped value can still be a credential (`ghp_...`,
                # `AKIA...`), so the value scan still runs (invariant audit).
                _reject_credentials(list(value.values()), here)
                continue
            if isinstance(key, str) and _SECRET_KEY_PATTERN.search(key) and value not in (None, ""):
                raise ManifestError(
                    f"{here}: looks like a credential. culprit.yaml names config keys, "
                    "never their values — see docs/DIAGNOSTIC_PLAN.md §2.7. Remove it; "
                    "if the model genuinely needs to reference this key, name it without "
                    "a value."
                )
            _reject_credentials(value, here)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_credentials(item, f"{path}[{index}]")
    elif isinstance(node, str):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(node):
                raise ManifestError(
                    f"{path or '<root>'}: value looks like a credential "
                    f"({pattern.pattern.split('(')[0][:24]}...). culprit.yaml is a "
                    "committed file; a credential in it is a credential leaked."
                )


#: cli/internal/model/divergence.go's severities.
_SEVERITIES = frozenset({"breaks_request_path", "degrades", "cosmetic", "unknown"})
_GO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _is_go_date(text: str) -> bool:
    """Go's time.Parse("2006-01-02", text): two-digit month and day."""
    if _GO_DATE.fullmatch(text) is None:
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _check_subject(where: str, subject: str) -> None:
    """cli/internal/extract/policy.go's checkSubject: a canonical subject
    URI, or a prefix pattern ending in `*` that names at least a kind. The
    subject is not repeated in the message."""
    if not subject.strip():
        raise ValueError(f"{where}: `subject` is required")
    if subject.endswith("*"):
        if ":" not in subject[:-1]:
            raise ValueError(f"{where}: a pattern must name at least a subject kind and component")
        return
    try:
        kind, parts = subjects.parse(subject)
        rebuilt = subjects.build(kind, **parts)
    except subjects.SubjectError:
        raise ValueError(f"{where}: not a subject URI") from None
    if rebuilt != subject:
        raise ValueError(f"{where}: not in canonical form")


class ConnectionSpec(BaseModel):
    """One outgoing edge, as written in the manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    to: str
    kind: ConnectionKind = ConnectionKind.HTTP
    criticality: Criticality = Criticality.UNKNOWN


class ComponentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=COMPONENT_NAME_PATTERN)
    kind: ComponentKind = ComponentKind.SERVICE
    display_name: str | None = None
    environments: tuple[str, ...] = ()
    labels: dict[str, Any] = Field(default_factory=dict)
    monitored_metrics: tuple[str, ...] = ()
    connections: tuple[ConnectionSpec, ...] = ()


class ExtractorSpec(BaseModel):
    """One extractor plugin command (Phase 28 field 10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    #: argv, never a shell string. A manifest is a committed file, and a
    #: command interpreted by a shell would make `culprit.yaml` an
    #: arbitrary-execution vector for anyone who can open a pull request.
    command: tuple[str, ...] = ()
    want: tuple[str, ...] = ()


class ComponentExtractSpec(BaseModel):
    """One component's extraction settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: str = ""
    extractors: tuple[str, ...] = ()
    artefacts: tuple[str, ...] = ()
    #: The component whose routes this one's HTTP client calls hit. See
    #: `cli/internal/extract/manifest.go` — a client-call extractor
    #: cannot work this out on its own, and without it those facts land
    #: under the caller and compare against nothing.
    calls_to: str = ""


class ExtractSpec(BaseModel):
    """The `extract:` section.

    **The control plane does not act on any of this.** Extraction runs
    in the `culprit` binary, against a checkout, with no control plane
    involved (Phase 28 field 3). This model exists so `apply-model`
    accepts a manifest that carries the section, and so `--export`
    round-trips it rather than silently deleting a user's extractor
    configuration — which is exactly what `extra="forbid"` would have
    done the first time somebody ran the documented
    `apply-model --export > culprit.yaml` workflow.

    It is validated all the same. A typo here is a source root that is
    never scanned, and every fact the author expected simply absent —
    which reads as "nothing wrong there".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    extractors: tuple[ExtractorSpec, ...] = ()
    components: dict[str, ComponentExtractSpec] = Field(default_factory=dict)


class ComposeEnvSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = ""
    files: tuple[str, ...] = ()


class KubernetesEnvSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context: str = ""
    namespace: str = ""


class DatabaseEnvSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The *name* of a variable holding a connection string, never the
    #: string — the same rule the Go loader enforces.
    dsn_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    name: str = ""


class EndpointEnvSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str
    port: int = Field(ge=1, le=65535)
    tls: bool = False
    #: Phase 32: the path the isolation walk requests at this component.
    #: Go's `validateEndpoint` rule: a path, no query string or credentials.
    health_path: str = Field(default="", pattern=r"^(/[^ @?#]*)?$")

    @field_validator("host")
    @classmethod
    def _a_bare_hostname(cls, host: str) -> str:
        """Go's validateEndpoint: not blank, and no `/`, `@`, `:` or space."""
        if not host.strip() or any(char in host for char in "/@: "):
            raise ValueError("a bare hostname, with no scheme, port or credentials")
        return host


class EnvironmentComponentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workload: str = ""
    container: str = ""
    env_command: str = ""
    packages: str = ""
    database: DatabaseEnvSpec | None = None
    endpoint: EndpointEnvSpec | None = None
    #: Phase 32: callee -> the *name* of the variable holding the bearer
    #: token this component presents to it. Never the token; the
    #: credential check (`_is_token_reference_map`) holds the same rule.
    tokens: dict[str, Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]] = (
        Field(default_factory=dict)
    )


class EnvironmentSpec(BaseModel):
    """One entry under `environments:` (Phase 30 field 10).

    **The control plane does not act on any of this**, exactly like
    `extract:`. Capture runs in the `culprit` binary, in whatever shell
    can reach the environment; this model exists so `apply-model` accepts
    a manifest that carries the section and `--export` round-trips it
    rather than deleting a user's grants. The Go loader
    (`cli/internal/extract/environments.go`) is the one that validates
    grants against §2.7 — this checks structure and names, and refuses a
    connection string where a variable name belongs, which the whole-file
    credential check would also catch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter: str = Field(pattern=r"^(compose|kubernetes|process|exec)$")
    compose: ComposeEnvSpec | None = None
    kubernetes: KubernetesEnvSpec | None = None
    exec: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    #: `true`/`false`, or an allowlist for the three per-item capabilities.
    #: Keyed by the closed §2.7 set — see `_check_grants`.
    grants: dict[Capability, bool | tuple[str, ...]] = Field(default_factory=dict)
    components: dict[str, EnvironmentComponentSpec] = Field(default_factory=dict)
    #: Phase 32: where the isolation walk reaches each component from the
    #: vantage `culprit diagnose` runs at. Not acted on here either.
    endpoints: dict[str, EndpointEnvSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_grants(self) -> "EnvironmentSpec":
        """The Go loader's grant rules, so `apply-model` accepts exactly the
        manifests `culprit env capture` does. An unknown name (including
        any `*.write`) already failed the `Capability` key type; here, a
        per-item capability must be a non-empty list of named items, and
        every other must be a bool."""
        for capability, grant in self.grants.items():
            if capability in ALLOWLISTED:
                if isinstance(grant, bool) or not grant or any("*" in item for item in grant):
                    raise ValueError(
                        f"grants.{capability}: needs an explicit, non-empty list of named items"
                    )
            elif not isinstance(grant, bool):
                raise ValueError(f"grants.{capability}: expected true or false")
        return self


class InvariantSpec(BaseModel):
    """`invariants:` (Phase 29): a developer's rank-100 assertion, which the
    `culprit` binary turns into an INTENT fact. Like `extract:` and
    `environments:`, structure only — the control plane does not act on
    it; it is here so `apply-model` accepts a manifest carrying it and
    `--export` keeps it. `cli/internal/extract/policy.go` is the loader that
    judges one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: Any = None
    why: str = ""


class SuppressionSpec(BaseModel):
    """`suppress:` (Phase 29). The reason is required, as in Go."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    predicate: str = ""
    reason: str = Field(min_length=1)
    expires: str = ""


class SeverityOverrideSpec(BaseModel):
    """`severity_overrides:` (Phase 29). The reason is required, as in Go."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    reason: str = Field(min_length=1)


#: A Go duration (`time.ParseDuration`): one or more numbers, each with a
#: unit. The Go loader also refuses zero, which `_positive_duration` checks.
_GO_DURATION = re.compile(r"(?:(?:\d+(?:\.\d*)?|\.\d+)(?:ns|us|µs|μs|ms|s|m|h))+")


def _positive_duration(text: str) -> bool:
    if _GO_DURATION.fullmatch(text) is None:
        return False
    return any(ch in "123456789" for ch in text)


class ProbeSpec(BaseModel):
    """One entry of `probes:` (Phase 31), as cli/internal/extract/probes.go
    reads and refuses it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool | None = None
    reason: str = ""
    timeout_ms: int = Field(default=0, ge=0, le=300_000)
    environments: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _a_disabled_probe_says_why(self) -> "ProbeSpec":
        if self.enabled is False and not self.reason.strip():
            raise ValueError(
                "a probe that is disabled gives a reason: a check switched off without one "
                "is indistinguishable from one nobody noticed was off"
            )
        return self


class IsolationEnvironmentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_probes: int = Field(default=0, ge=0)


class IsolationSpec(BaseModel):
    """`isolation:` (Phase 32 field 10), as cli/internal/extract/isolation.go
    reads and refuses it: bounds on `culprit diagnose`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_probes: int = Field(default=0, ge=0)
    max_wall_clock: str = ""
    environments: dict[str, IsolationEnvironmentSpec] = Field(default_factory=dict)

    @field_validator("max_wall_clock")
    @classmethod
    def _a_duration(cls, value: str) -> str:
        if value and not _positive_duration(value):
            raise ValueError("isolation.max_wall_clock: a duration such as 2m or 90s")
        return value


class Manifest(BaseModel):
    """A whole `culprit.yaml`, validated.

    `extra="forbid"` throughout: a typo'd key in a manifest is the
    difference between a modelled connection and an unmodelled one, and
    silently ignoring `criticallity:` would leave the author certain they
    had classified an edge they had not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = MANIFEST_VERSION
    components: tuple[ComponentSpec, ...] = ()
    #: Phase 28. Validated here, carried through load/dump untouched, and
    #: never acted on by the control plane — see ExtractSpec.
    extract: ExtractSpec | None = None
    #: Phase 30. Same treatment as `extract` — see EnvironmentSpec.
    environments: dict[str, EnvironmentSpec] | None = None
    #: Phase 29's three policy sections — accepted and round-tripped, not
    #: acted on here (see InvariantSpec). Until Phase 32 part 2 they were
    #: missing, so `apply-model` refused any manifest carrying one.
    invariants: tuple[InvariantSpec, ...] = ()
    suppress: tuple[SuppressionSpec, ...] = ()
    severity_overrides: tuple[SeverityOverrideSpec, ...] = ()
    #: Phase 36: how fast a subject must be, as `culprit_model.latency.Budget`
    #: judges an entry — an unknown predicate is refused here as in Go. Like
    #: `invariants`, accepted and round-tripped, not acted on here; until it
    #: was added, `apply-model` refused any manifest carrying one.
    budgets: tuple[Budget, ...] = ()
    #: Phase 31 and Phase 32, read by the Go loader since then and missing
    #: here until Phase 37 part 1: a user who set either broke `apply-model`.
    #: Validated as the Go loader validates them, carried through load and
    #: export, never acted on here. `shared/tests/manifest_keys.json` holds
    #: the two readers to one list of top-level keys.
    probes: dict[str, ProbeSpec] | None = None
    isolation: IsolationSpec | None = None

    @model_validator(mode="after")
    def _check_probes_and_isolation(self) -> "Manifest":
        """The cross-references the Go loader checks (probes.go,
        isolation.go): an environment named in either must be declared."""
        declared = set(self.environments or {})
        for probe_id, spec in (self.probes or {}).items():
            for environment in spec.environments:
                if environment not in declared:
                    raise ValueError(
                        f"probes.{probe_id} names environment {environment!r}, "
                        "which is not declared under environments:"
                    )
        if self.isolation is not None:
            for environment in self.isolation.environments:
                if environment not in declared:
                    raise ValueError(
                        f"isolation.environments.{environment}: not an environment "
                        "declared under environments:"
                    )
        return self

    @model_validator(mode="after")
    def _check_environment_components(self) -> "Manifest":
        """Every component an environment names must be declared here —
        refused rather than ignored, matching the Go loader, for the reason
        `_check_extract_references` gives: a silently unmatched name is a
        capture that quietly looks at nothing."""
        if not self.environments:
            return self
        known = {component.name for component in self.components}
        for name, spec in self.environments.items():
            unknown = sorted(set(spec.components) - known)
            if unknown:
                raise ValueError(
                    f"environments.{name}.components: {unknown} are not declared in this file"
                )
        return self

    @model_validator(mode="after")
    def _check_environments_as_go_does(self) -> "Manifest":
        """cli/internal/extract/environments.go's rules, which this model did
        not hold until the differential corpus found them (Q28): a manifest
        `culprit env capture` refuses is refused here too."""
        known = {component.name for component in self.components}
        for name, spec in (self.environments or {}).items():
            where = f"environments.{name}"
            if not name.strip() or any(char in name for char in " /\\"):
                raise ValueError(
                    f"{where}: an environment name may not be blank or contain spaces or slashes"
                )
            allowlist = spec.grants.get(Capability("process.exec.allowlist"), ())
            for command, argv in spec.exec.items():
                if not argv or not argv[0].strip():
                    raise ValueError(f"{where}.exec.{command}: an empty command")
                if isinstance(allowlist, bool) or command not in allowlist:
                    raise ValueError(
                        f"{where}.exec.{command}: declared but not in "
                        "grants.process.exec.allowlist, "
                        "so it can never run"
                    )
            if not spec.components:
                raise ValueError(f"{where}.components: name at least one component to capture")
            if spec.adapter == "process" and len(spec.components) != 1:
                raise ValueError(
                    f"{where}: the process adapter captures one component's environment; name one"
                )
            for component, settings in spec.components.items():
                at = f"{where}.components.{component}"
                for field, command in (
                    ("env_command", settings.env_command),
                    ("packages", settings.packages),
                ):
                    if command and command not in spec.exec:
                        raise ValueError(
                            f"{at}.{field}: names a command not declared under {where}.exec"
                        )
                if spec.adapter == "exec" and not settings.env_command:
                    raise ValueError(
                        f"{at}.env_command: the exec adapter reads a component's "
                        "environment from a command"
                    )
                for callee in settings.tokens:
                    if callee not in known:
                        raise ValueError(f"{at}.tokens: {callee!r} is not a component in this file")
            for component in spec.endpoints:
                if component not in known:
                    raise ValueError(f"{where}.endpoints.{component}: not a component in this file")
        return self

    @model_validator(mode="after")
    def _check_policy_as_go_does(self) -> "Manifest":
        """cli/internal/extract/policy.go's rules for invariants, suppressions
        and severity overrides (Q28): reasons and whys that are only spaces
        are missing, a subject must parse and be canonical (or be a prefix
        pattern naming at least a kind), a date is YYYY-MM-DD."""
        for index, invariant in enumerate(self.invariants):
            where = f"invariants[{index}]"
            if not invariant.why.strip():
                raise ValueError(f"{where}: `why` is required")
            if not invariant.predicate.strip():
                raise ValueError(f"{where}: `predicate` is required")
            _check_subject(where, invariant.subject)
        for index, suppression in enumerate(self.suppress):
            where = f"suppress[{index}]"
            if not suppression.reason.strip():
                raise ValueError(f"{where}: `reason` is required")
            _check_subject(where, suppression.subject)
            if suppression.expires and not _is_go_date(suppression.expires):
                raise ValueError(f"{where}: `expires` is not a YYYY-MM-DD date")
        for index, override in enumerate(self.severity_overrides):
            where = f"severity_overrides[{index}]"
            if not override.reason.strip():
                raise ValueError(f"{where}: `reason` is required")
            if override.severity not in _SEVERITIES:
                raise ValueError(f"{where}: severity is not one of {sorted(_SEVERITIES)}")
            _check_subject(where, override.subject)
        return self

    @model_validator(mode="after")
    def _check_statement_budgets(self) -> "Manifest":
        """A `query_mean_ms_max` budget (Phase 37 part 2) is on a table —
        `schema:<database>/<ns>.<table>`, no column — or on the database's
        component, and either way on a component this file declares as a
        database. cli/internal/extract/budgets.go holds the same rule."""
        databases = {c.name for c in self.components if c.kind == ComponentKind.DATABASE}
        for index, budget in enumerate(self.budgets):
            if budget.predicate not in STATEMENT_BUDGET_PREDICATES:
                continue
            where = f"budgets[{index}]"
            kind, parts = subjects.parse(budget.subject)
            if kind == subjects.SubjectKind.SCHEMA:
                if parts.get("column"):
                    raise ValueError(
                        f"{where}: a statement budget is on a table or a database, not on a column"
                    )
                database = parts["database"]
            elif kind == subjects.SubjectKind.COMPONENT:
                database = parts["name"]
            else:
                raise ValueError(
                    f"{where}: a statement budget is on a table "
                    "(schema:<database>/<namespace>.<table>) or on a database component"
                )
            if database not in databases:
                raise ValueError(
                    f"{where}: {database} is not a component of kind database in this file"
                )
        return self

    @model_validator(mode="after")
    def _check_budgets_are_not_repeated(self) -> "Manifest":
        """One budget per subject and predicate in a file, as the Go loader
        holds: two would be one source saying two things, and one of them
        would be measured and the other dropped without a word."""
        seen: set[tuple[str, str]] = set()
        for index, budget in enumerate(self.budgets):
            key = (budget.subject, budget.predicate)
            if key in seen:
                raise ValueError(
                    f"budgets[{index}] repeats an earlier budget: one subject and "
                    "predicate may have one budget in a file"
                )
            seen.add(key)
        return self

    @model_validator(mode="after")
    def _check_version(self) -> "Manifest":
        if self.version != MANIFEST_VERSION:
            raise ValueError(
                f"unsupported culprit.yaml version {self.version} "
                f"(this build understands version {MANIFEST_VERSION})"
            )
        return self

    @model_validator(mode="after")
    def _check_unique_names(self) -> "Manifest":
        counts = Counter(component.name for component in self.components)
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate component name(s): {duplicates}")
        return self

    @model_validator(mode="after")
    def _check_targets_exist(self) -> "Manifest":
        """Every connection target must be a component in the same file.

        This is the manifest-level form of `SystemGraph`'s own endpoint
        check. It lives here as well as there so the error names the
        *file's* problem ("you referenced a component you did not
        declare") rather than surfacing as a graph construction failure
        several layers away.
        """
        known = {c.name for c in self.components}
        dangling = sorted(
            {
                f"{component.name} -> {connection.to}"
                for component in self.components
                for connection in component.connections
                if connection.to not in known
            }
        )
        if dangling:
            raise ValueError(
                f"connection target(s) not declared in this file: {dangling}. "
                "Declare the target as a component, even a bare `- name: x`."
            )
        return self

    @model_validator(mode="after")
    def _check_extract_references(self) -> "Manifest":
        """Every name in `extract:` must be something this file declares.

        Refused rather than ignored, matching the Go loader exactly. An
        `extract.components` entry naming a component that is not in the
        file means the author believes a root is being scanned that is
        not; a `calls_to` pointing at nothing means client-call facts
        stay on the caller's subject and compare against nothing. Both
        fail silently as "fewer findings", which is the worst way for a
        configuration mistake to present.
        """
        if self.extract is None:
            return self
        known = {component.name for component in self.components}

        # The extractor list itself, checked the way the Go loader checks
        # it. The docstring above used to claim the two matched exactly
        # while these three rules existed only on the Go side, so
        # `apply-model` accepted manifests `culprit intent` refuses —
        # a file that passes the server and fails the tool is worse than
        # one that fails both. (Found by the Phase 28 invariant audit.)
        seen_extractors: set[str] = set()
        for spec in self.extract.extractors:
            if not spec.name.strip():
                raise ValueError("extract.extractors: an entry has no name")
            if not spec.command:
                raise ValueError(f"extract.extractors.{spec.name}: command is empty")
            if spec.name in seen_extractors:
                raise ValueError(f"extract.extractors: duplicate name {spec.name}")
            seen_extractors.add(spec.name)

        extractors = seen_extractors
        for name, spec in self.extract.components.items():
            if name not in known:
                raise ValueError(
                    f"extract.components.{name}: no component named {name} is declared in this file"
                )
            unknown = sorted(set(spec.extractors) - extractors)
            if unknown:
                raise ValueError(
                    f"extract.components.{name}: extractor(s) {unknown} are not declared "
                    "in extract.extractors"
                )
            if spec.calls_to and spec.calls_to not in known:
                raise ValueError(
                    f"extract.components.{name}: calls_to names {spec.calls_to}, which is "
                    "not a component in this file"
                )
        return self

    def to_graph(self) -> SystemGraph:
        """The manifest as the in-memory model.

        `declared_by` is `culprit_yaml` for every edge here by
        definition — this *is* the declarative source.
        """
        return SystemGraph(
            components=tuple(
                Component(
                    name=spec.name,
                    kind=spec.kind,
                    environment_scope=spec.environments,
                    labels=spec.labels,
                )
                for spec in self.components
            ),
            connections=tuple(
                Connection(
                    from_component=spec.name,
                    to_component=connection.to,
                    kind=connection.kind,
                    declared_by=DeclaredBy.CULPRIT_YAML,
                    criticality=connection.criticality,
                )
                for spec in self.components
                for connection in spec.connections
            ),
        )


class YAML12Loader(yaml.SafeLoader):
    """PyYAML's safe loader, used only to *compose*: to parse, and to give
    each plain scalar the tag the Go loader's yaml.v3 gives it.

    PyYAML implements YAML 1.1, where `yes` is a boolean, a date is a date
    and `0o454` is a string. yaml.v3 reads YAML 1.2's core schema with Go's
    number parsing. `resolve` below ports yaml.v3's own resolver
    (`resolve.go`), branch for branch, so both readers see one tag for one
    scalar. The differential corpus (shared/tests/manifest_corpus.json)
    holds the two equal across every field and every scalar form.

    Nothing is constructed by PyYAML: `_typed` builds the manifest's values
    from the composed nodes and knows only plain data's tags, so no tag can
    make an object (CodeQL py/unsafe-deserialization, Phase 37 part 1
    close-out).
    """

    def resolve(self, kind: Any, value: Any, implicit: Any) -> Any:
        if kind is yaml.ScalarNode:
            if implicit[0]:
                return _TAG + _v3_resolve(value)[0]
            return _TAG + "str"
        return super().resolve(kind, value, implicit)


_TAG = "tag:yaml.org,2002:"

#: yaml.v3's resolveMap: the scalars it reads by lookup alone.
_V3_MAP: dict[str, tuple[str, object]] = {
    **{word: ("bool", True) for word in ("true", "True", "TRUE")},
    **{word: ("bool", False) for word in ("false", "False", "FALSE")},
    **{word: ("null", None) for word in ("", "~", "null", "Null", "NULL")},
    **{word: ("float", math.nan) for word in (".nan", ".NaN", ".NAN")},
    **{word: ("float", math.inf) for word in (".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF")},
    **{word: ("float", -math.inf) for word in ("-.inf", "-.Inf", "-.INF")},
    "<<": ("merge", "<<"),
}
#: Go's ParseInt/ParseUint with base 0, once yaml.v3 has removed every `_`.
_GO_INT = re.compile(r"([+-]?)(0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|0[0-7]*|[1-9][0-9]*)")
#: yaml.v3's yamlStyleFloat, and the decimal floats Go's ParseFloat reads.
_YAML_STYLE_FLOAT = re.compile(r"[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?")
#: yaml.v3 tries a timestamp only for text that starts with four digits and
#: a dash. Such text is never a number, and a timestamp is text here (Q28),
#: so it is text either way.
_DATE_LIKE = re.compile(r"[0-9]{4}-")


def _go_int(text: str, *, signed: bool) -> int | None:
    match = _GO_INT.fullmatch(text)
    if match is None or (match.group(1) and not signed):
        return None
    sign, digits = match.groups()
    prefix = digits[:2].lower()
    if prefix in ("0x", "0b", "0o"):
        value = int(digits[2:], {"0x": 16, "0b": 2, "0o": 8}[prefix])
    elif len(digits) > 1 and digits[0] == "0":
        value = int(digits[1:], 8)
    else:
        value = int(digits, 10)
    value = -value if sign == "-" else value
    if signed:
        return value if -(2**63) <= value < 2**63 else None
    return value if value < 2**64 else None


def _go_float(text: str) -> float | None:
    """Go's ParseFloat for the decimal forms yaml.v3 hands it; a value out
    of range is an error there, not an infinity."""
    if _YAML_STYLE_FLOAT.fullmatch(text) is None:
        return None
    value = float(text)
    return None if math.isinf(value) else value


def _v3_resolve(text: str) -> tuple[str, object]:
    """yaml.v3's resolve("", text): the short tag and value of a plain
    scalar, by the first character's hint, as resolve.go decides it."""
    if text in _V3_MAP:
        return _V3_MAP[text]
    hint = text[0]
    if hint == ".":
        value = _go_float(text)
        return ("float", value) if value is not None else ("str", text)
    if hint in "+-0123456789":
        if _DATE_LIKE.match(text):
            return "str", text
        plain = text.replace("_", "")
        for signed in (True, False):
            number = _go_int(plain, signed=signed)
            if number is not None:
                return "int", number
        value = _go_float(plain)
        if value is not None:
            return "float", value
    return "str", text


def _refuse(node: yaml.Node, problem: str) -> "ManifestError":
    """A refusal naming the field and the line, never the value."""
    return ManifestError(f"{problem} (line {node.start_mark.line + 1})")


def _scalar(node: yaml.ScalarNode, path: str) -> tuple[str, object]:
    """A scalar's kind (str, int, float, bool, null) and value, as yaml.v3
    decodes it: an explicit tag must agree with what the text resolves to
    (`!!float` also takes an integer); `!!str` takes any text. Any other
    tag — `!!binary`, `!!timestamp`, `!!python/...` — is not plain data.
    The value is never put in a message (invariant 7)."""
    short = node.tag[len(_TAG) :] if node.tag.startswith(_TAG) else None
    if short == "str":
        return "str", node.value
    if short not in ("int", "float", "bool", "null"):
        raise _refuse(node, f"{path}: a value tagged {node.tag} is not plain data")
    kind, value = _v3_resolve(node.value)
    if short == "float" and kind == "int" and isinstance(value, int):
        return "float", float(value)
    if kind != short:
        raise _refuse(node, f"{path}: the text cannot be read as !!{short}")
    return kind, value


def _repeated_key(node: yaml.MappingNode, path: str) -> None:
    """yaml.v3's uniqueKeys: no mapping holds two keys of one kind and text."""
    seen: set[tuple[type, str]] = set()
    for key, _ in node.value:
        identity = (type(key), key.value if isinstance(key, yaml.ScalarNode) else "")
        if identity in seen:
            raise _refuse(key, f"{path or '<root>'}: a key is written twice in one mapping")
        seen.add(identity)


def _pairs(node: yaml.MappingNode, path: str) -> list[tuple[str, yaml.Node, yaml.Node]]:
    """A mapping's pairs in yaml.v3's order — its own keys, then what each
    merge (`<<`) brings in, a merged mapping's own keys before its merges —
    where the first to set a key wins. Every key must be text."""
    _repeated_key(node, path)
    own: list[tuple[str, yaml.Node, yaml.Node]] = []
    merges: list[yaml.Node] = []
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode) and key.tag == _TAG + "merge":
            merges.append(value)
            continue
        if not isinstance(key, yaml.ScalarNode) or _scalar(key, path)[0] != "str":
            raise _refuse(key, f"{path or '<root>'}: every key is text")
        own.append((key.value, key, value))
    for merged in merges:
        items = merged.value if isinstance(merged, yaml.SequenceNode) else [merged]
        for item in items:
            if not isinstance(item, yaml.MappingNode):
                raise _refuse(item, f"{path or '<root>'}: a merge (<<) of something not a mapping")
            own.extend(_pairs(item, path))
    first: dict[str, tuple[str, yaml.Node, yaml.Node]] = {}
    for entry in own:
        first.setdefault(entry[0], entry)
    return list(first.values())


#: What one manifest field holds (Q28: one type per field).
Schema = tuple[str, Any]


def _schema_of(annotation: Any) -> Schema:
    """The type a model field holds, as the corpus and the Go loader see it:
    `str`, `int`, `bool`, `any`, `grant` (true, false or a list of text),
    a list, a map from text, or a struct of named fields."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _schema_of(args[0])
    if origin in (typing.Union, types.UnionType):
        present = [arg for arg in args if arg is not type(None)]
        if len(present) == 1:
            return _schema_of(present[0])
        if set(map(typing.get_origin, present)) | set(present) >= {bool, tuple}:
            return ("grant", None)
        raise TypeError(f"no manifest type for {annotation}")
    if origin in (tuple, list):
        return ("list", _schema_of(args[0]))
    if origin is dict:
        return ("map", _schema_of(args[1]))
    if annotation is Any:
        return ("any", None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return (
            "struct",
            {
                (field.alias or name): _schema_of(field.annotation)
                for name, field in annotation.model_fields.items()
            },
        )
    if isinstance(annotation, type) and issubclass(annotation, bool):
        return ("bool", None)
    if isinstance(annotation, type) and issubclass(annotation, int):
        return ("int", None)
    if isinstance(annotation, type) and issubclass(annotation, str):
        return ("str", None)  # str, and every str enum
    raise TypeError(f"no manifest type for {annotation}")


@functools.cache
def _manifest_type() -> Schema:
    return _schema_of(Manifest)


def manifest_schema() -> dict[str, str]:
    """Every field's path and type, flat: what shared/tests/manifest_schema.json
    holds, and what the Go loader's own derivation is held to."""
    flat: dict[str, str] = {}

    def walk(schema: Schema, path: str) -> None:
        kind, inner = schema
        if kind == "struct":
            for name, field in inner.items():
                walk(field, f"{path}.{name}" if path else name)
        elif kind == "list":
            walk(inner, path + "[]")
        elif kind == "map":
            walk(inner, path + "{}")
        else:
            flat[path] = kind

    walk(_manifest_type(), "")
    return flat


_KIND_NAMES = {"str": "text", "int": "an integer", "bool": "true or false"}


def _typed(node: yaml.Node, schema: Schema, path: str) -> object:
    """The node as plain data of the type the field holds, or refused,
    naming the field. Null and empty are refused everywhere: leaving a key
    out is how a manifest says "not set" (Q28)."""
    kind, inner = schema
    where = path or "<root>"
    if isinstance(node, yaml.ScalarNode):
        found, value = _scalar(node, where)
        if found == "null":
            raise _refuse(node, f"{where}: null or empty; leave the key out to leave it unset")
        if kind == "grant":
            kind = "bool"
        if kind == "any":
            if found == "int" and isinstance(value, int) and not -(2**63) <= value < 2**63:
                raise _refuse(node, f"{where}: an integer out of range")
            return value
        if kind in _KIND_NAMES:
            if found != kind:
                raise _refuse(node, f"{where}: expected {_KIND_NAMES[kind]}, written as {found}")
            if kind == "int" and isinstance(value, int) and not -(2**63) <= value < 2**63:
                raise _refuse(node, f"{where}: an integer out of range")
            return value
        raise _refuse(
            node, f"{where}: expected a {'mapping' if kind in ('struct', 'map') else 'list'}"
        )
    if isinstance(node, yaml.SequenceNode):
        if node.tag != _TAG + "seq":
            raise _refuse(node, f"{where}: a value tagged {node.tag} is not plain data")
        if kind == "grant":
            return [
                _typed(item, ("str", None), f"{path}[{i}]") for i, item in enumerate(node.value)
            ]
        if kind not in ("list", "any"):
            raise _refuse(node, f"{where}: a list where the field is not one")
        element = inner if kind == "list" else ("any", None)
        return [_typed(item, element, f"{path}[{i}]") for i, item in enumerate(node.value)]
    if isinstance(node, yaml.MappingNode):
        if node.tag != _TAG + "map":
            raise _refuse(node, f"{where}: a value tagged {node.tag} is not plain data")
        if kind not in ("struct", "map", "any"):
            raise _refuse(node, f"{where}: a mapping where the field is not one")
        out: dict[str, object] = {}
        for name, key, value in _pairs(node, path):
            field_path = f"{path}.{name}" if path else name
            if kind == "struct":
                if name not in inner:
                    raise _refuse(key, f"{where}: unknown key {name!r}")
                out[name] = _typed(value, inner[name], field_path)
            else:
                out[name] = _typed(value, inner if kind == "map" else ("any", None), field_path)
        return out
    raise _refuse(node, f"{where}: not plain data")


def typed_document(text: str, *, source: str = "culprit.yaml") -> dict[str, object]:
    """The manifest as typed plain data, before the model's own checks:
    what the differential corpus compares with the Go loader's."""
    return _typed_root(_compose(text, source), source)


def _compose(text: str, source: str) -> yaml.Node:
    try:
        root = yaml.compose(text, Loader=YAML12Loader)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{source}: not valid YAML:\n{exc}") from exc
    if root is None:
        raise ManifestError(f"{source}: empty")
    return root


def _typed_root(root: yaml.Node, source: str) -> dict[str, object]:
    try:
        document = _typed(root, _manifest_type(), "")
    except ManifestError as exc:
        raise ManifestError(f"{source}: {exc}") from None
    assert isinstance(document, dict)
    return document


def _reject_budget_literals(root: yaml.Node, text: str, source: str) -> None:
    """Refuses a `budgets:` value not written as plain decimal digits
    (Phase 36 part 2), reading the YAML as the Go loader (yaml.v3) reads it,
    so the two readers of one file never read two values or one load what
    the other refuses (Phase 37 part 1, the re-audit of 4c7bc6e):

    - a key written twice in any mapping — `<<` included, compared by tag
      and value — is refused, as yaml.v3 refuses it, where PyYAML would keep
      the last;
    - the form is checked on the `budgets:` section the Go loader reads: the
      root's own key when it has one, otherwise the first a merge brings in,
      in merge order. A section a direct key overrides is never read by
      either, so it is not checked.

    Read from the YAML node, not the parsed value: this reader (YAML 1.1)
    takes `0454` for octal 300 and `300_000` for 300000, where the Go loader
    reads 454 and a string, so the form is what is checked — by
    `culprit_model.latency.budget_literal_problem`, which the Go loader's
    twin is held to with it."""
    if not isinstance(root, yaml.MappingNode):
        return
    _reject_repeated_keys(root, source)
    section = _budgets_section(root)
    if not isinstance(section, yaml.SequenceNode):
        return
    for index, entry in enumerate(section.value):
        if not isinstance(entry, yaml.MappingNode):
            continue
        for field, value in entry.value:
            if field.tag == "tag:yaml.org,2002:merge" or field.value == "<<":
                # The fields a merge brings in are not checked for their
                # form; the Go loader refuses it too.
                raise ManifestError(f"{source}: budgets[{index}]: {BUDGET_MERGE_PROBLEM}")
            if field.value != "value":
                continue
            # Plain: an unquoted scalar with no explicit tag, anchor or
            # alias. An alias composes to the node it names, so it is caught
            # by the anchor PyYAML leaves on that node.
            plain = (
                isinstance(value, yaml.ScalarNode)
                and value.style is None
                and not _tagged(text, value)
            )
            literal = value.value if isinstance(value, yaml.ScalarNode) else ""
            problem = budget_literal_problem(literal, plain)
            if problem is not None:
                raise ManifestError(f"{source}: budgets[{index}]: value: {problem}")


def _is_merge(key: yaml.Node) -> bool:
    return key.tag == "tag:yaml.org,2002:merge" or (
        isinstance(key, yaml.ScalarNode) and key.value == "<<" and key.style is None
    )


def _reject_repeated_keys(root: yaml.Node, source: str) -> None:
    """yaml.v3's rule, which PyYAML does not keep: no mapping holds the same
    scalar key twice, compared by its resolved tag and its value. Every
    mapping in the document, the merge key included."""
    pending: list[yaml.Node] = [root]
    seen: set[int] = set()
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys: set[tuple[str, str]] = set()
            for key, value in node.value:
                if isinstance(key, yaml.ScalarNode):
                    identity = (key.tag, key.value)
                    if identity in keys:
                        raise ManifestError(
                            f"{source}: the key {key.value!r} is written twice in one mapping"
                        )
                    keys.add(identity)
                pending.extend((key, value))
        elif isinstance(node, yaml.SequenceNode):
            pending.extend(node.value)


def _budgets_section(mapping: yaml.MappingNode) -> yaml.Node | None:
    """The `budgets:` section the Go loader reads from this mapping: its own
    key, or else the first one a merge brings in, in merge order (an
    earlier mapping in `<<: [a, b]` wins over a later one)."""
    for key, value in mapping.value:
        if not _is_merge(key) and key.value == "budgets":
            return value
    for key, value in mapping.value:
        if not _is_merge(key):
            continue
        merged = value.value if isinstance(value, yaml.SequenceNode) else [value]
        for node in merged:
            if isinstance(node, yaml.MappingNode):
                found = _budgets_section(node)
                if found is not None:
                    return found
    return None


def _tagged(text: str, node: yaml.ScalarNode) -> bool:
    """Whether the scalar was written with an explicit tag or as an alias:
    the composed node does not say, so the source between its marks is
    read. A plain scalar's source is exactly its value."""
    start, end = node.start_mark.index, node.end_mark.index
    return text[start:end] != node.value


def load_manifest(text: str, *, source: str = "culprit.yaml") -> Manifest:
    """Parses and validates a manifest. Pure — no filesystem access."""
    # As the Go loader (yaml.v3) reads it: composed, every plain scalar
    # resolved as yaml.v3 resolves it (YAML12Loader), then built as typed
    # plain data — one type per field, null refused (Q28). PyYAML
    # constructs nothing.
    if "	" in text:
        # yaml.v3 and PyYAML disagree on where a tab may stand; the binary
        # refuses one anywhere, and so does this (Q28).
        raise ManifestError(f"{source}: holds a tab character; indent and separate with spaces")
    root = _compose(text, source)
    # The budget's form first, from the node: a value not written as plain
    # decimal digits is refused for its form, whatever it would type as.
    _reject_budget_literals(root, text, source)
    raw = _typed_root(root, source)

    # Before validation, not after: a credential in a field the schema
    # would reject anyway must still be reported as a credential, and a
    # credential in a field the schema accepts must never reach a model
    # instance that something might log.
    _reject_credentials(raw)

    try:
        return Manifest.model_validate(raw)
    except ValidationError as exc:
        # Location and message only — never pydantic's default rendering,
        # which appends `input_value=...` for every error. The Phase 30
        # invariant audit showed why that matters here: `dsn_env:
        # postgresql://app@db/orders?password=hunter2` gets past
        # `_reject_credentials` (which matches the `user:pass@` form) and
        # then failed the `dsn_env` pattern — and the default message
        # echoed the whole connection string into `POST /model/apply`'s
        # 400 and `just apply-model`'s stderr. Standing invariant 11:
        # error text is output. Same rendering as app/model/envelope.py.
        where = "\n".join(
            "  "
            + ".".join(str(part) for part in error.get("loc", ()))
            + f": {error.get('msg', 'invalid')}"
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        )
        raise ManifestError(f"{source}: does not match the culprit.yaml schema:\n{where}") from exc


def read_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"{path}: cannot be read: {exc}") from exc
    return load_manifest(text, source=str(path))


def dump_manifest(manifest: Manifest) -> str:
    """The inverse of `load_manifest`, for `culprit.yaml` round-tripping
    (Phase 27's second acceptance criterion: apply, export, diff empty).

    Defaults are omitted rather than written out. An exported file that
    spells out `criticality: unknown` on every edge round-trips
    identically but is a worse document than the one the user wrote, and
    "diff is empty" has to mean empty against a file a human would
    actually commit.
    """
    components: list[dict[str, Any]] = []
    # Manifest order is preserved, not re-sorted: app/model/service.py's
    # export_manifest already hands components over in the author's own
    # order (stored as sort_order on apply), and alphabetising here would
    # undo that and break the round trip in acceptance criterion 2.
    for spec in manifest.components:
        entry: dict[str, Any] = {"name": spec.name}
        if spec.kind is not ComponentKind.SERVICE:
            entry["kind"] = str(spec.kind)
        if spec.display_name is not None:
            entry["display_name"] = spec.display_name
        if spec.environments:
            entry["environments"] = list(spec.environments)
        if spec.labels:
            entry["labels"] = dict(spec.labels)
        if spec.monitored_metrics:
            entry["monitored_metrics"] = list(spec.monitored_metrics)
        if spec.connections:
            entry["connections"] = [
                _dump_connection(connection)
                for connection in sorted(spec.connections, key=lambda c: (c.to, str(c.kind)))
            ]
        components.append(entry)

    document: dict[str, Any] = {"version": manifest.version, "components": components}
    # Phase 28: emitted only when present, and emitted *whole*.
    #
    # The alternative — dropping it, since the control plane does not act
    # on it — is the same defect Phase 27's audit found in `declared_by`:
    # the documented `apply-model --export > culprit.yaml` workflow would
    # silently delete the user's extractor configuration, and the next
    # `culprit intent` would report every source as skipped with nobody
    # able to say why.
    if manifest.extract is not None:
        document["extract"] = _dump_extract(manifest.extract)
    # Phase 30: carried whole, for the same reason as `extract` — the
    # control plane does not store it, and an export that dropped it would
    # delete a user's grants the first time they round-tripped the file.
    if manifest.environments is not None:
        document["environments"] = {
            name: manifest.environments[name].model_dump(
                mode="json", exclude_defaults=True, exclude_none=True
            )
            for name in sorted(manifest.environments)
        }
    # Phase 29's policy sections, carried in order for the same reason:
    # an export that dropped them would delete a team's suppressions, each
    # with the reason someone wrote for it.
    for section in ("invariants", "suppress", "severity_overrides", "budgets"):
        entries = getattr(manifest, section)
        if entries:
            document[section] = [
                entry.model_dump(mode="json", exclude_defaults=True) for entry in entries
            ]
    # Phase 37 part 1: carried whole for the same reason, now that this
    # model knows them.
    if manifest.probes is not None:
        document["probes"] = {
            probe_id: manifest.probes[probe_id].model_dump(
                mode="json", exclude_defaults=True, exclude_none=True
            )
            for probe_id in sorted(manifest.probes)
        }
    if manifest.isolation is not None:
        document["isolation"] = manifest.isolation.model_dump(mode="json", exclude_defaults=True)

    return yaml.safe_dump(
        document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _dump_extract(extract: "ExtractSpec") -> dict[str, Any]:
    """The `extract:` section, defaults omitted, in a stable order."""
    section: dict[str, Any] = {}
    if extract.extractors:
        section["extractors"] = [
            {
                key: value
                for key, value in (
                    ("name", spec.name),
                    ("command", list(spec.command)),
                    ("want", list(spec.want)),
                )
                if value
            }
            for spec in extract.extractors
        ]
    if extract.components:
        # Sorted: a mapping has no authored order to preserve, unlike the
        # components list, so an arbitrary one would make the export
        # differ between runs and break the round-trip criterion.
        # `entry or {}`, not a filter on truthiness. An all-default entry
        # (`culprit-worker: {}`) is a deliberate statement — "this
        # component is configured for extraction and takes the defaults"
        # — and dropping it from the export silently changes the file's
        # meaning, which is the same class of loss the surrounding
        # comments were written to prevent.
        section["components"] = {
            name: _dump_component_extract(extract.components[name]) or {}
            for name in sorted(extract.components)
        }
    return section


def _dump_component_extract(spec: "ComponentExtractSpec") -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if spec.root:
        entry["root"] = spec.root
    if spec.extractors:
        entry["extractors"] = list(spec.extractors)
    if spec.artefacts:
        entry["artefacts"] = list(spec.artefacts)
    if spec.calls_to:
        entry["calls_to"] = spec.calls_to
    return entry


def _dump_connection(connection: ConnectionSpec) -> dict[str, Any]:
    entry: dict[str, Any] = {"to": connection.to}
    if connection.kind is not ConnectionKind.HTTP:
        entry["kind"] = str(connection.kind)
    if connection.criticality is not Criticality.UNKNOWN:
        entry["criticality"] = str(connection.criticality)
    return entry
