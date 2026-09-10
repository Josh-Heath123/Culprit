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

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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

    host: str = Field(pattern=r"^[^/@:\s]+$")
    port: int = Field(ge=1, le=65535)
    tls: bool = False


class EnvironmentComponentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workload: str = ""
    container: str = ""
    env_command: str = ""
    packages: str = ""
    database: DatabaseEnvSpec | None = None
    endpoint: EndpointEnvSpec | None = None


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
                    f"extract.components.{name}: no component named {name} is declared "
                    "in this file"
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


def load_manifest(text: str, *, source: str = "culprit.yaml") -> Manifest:
    """Parses and validates a manifest. Pure — no filesystem access."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{source}: not valid YAML:\n{exc}") from exc

    if raw is None:
        raise ManifestError(f"{source}: empty")
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: expected a mapping at the top level")

    # Before validation, not after: a credential in a field the schema
    # would reject anyway must still be reported as a credential, and a
    # credential in a field the schema accepts must never reach a model
    # instance that something might log.
    _reject_credentials(raw)

    try:
        return Manifest(**raw)
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
