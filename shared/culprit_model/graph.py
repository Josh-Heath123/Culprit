"""The system model as a directed graph — components, typed connections,
and the request paths through them.

docs/DIAGNOSTIC_PLAN.md Phase 27. This is the vision's central
abstraction made computable: *a component can be healthy while a
connection is broken*. The old `service_dependencies` table could not
express that, because an untyped pair of service ids has nothing to be
broken about. A `Connection` has a kind, a criticality and (from Phase
28) a contract, so "orders-svc is up, and its SQL connection to orders-db
is fine, and its HTTP connection to payments-svc is the thing that
diverged" is a sentence this module can produce.

Pure, no I/O, mirroring the `scorer.py`/`state.py` split already
established in `worker/app/anomaly/`: the API layer loads rows and hands
them here, and every function below is a deterministic function of its
arguments. That is what makes it table-testable, and being table-testable
is what makes the severity computation in Phase 29 trustworthy.

**Why plain dictionaries and not `networkx`.** Phase 27's field 11 says
"no new dependencies — networkx is already present". It is present in
`worker/`, and only there. This module lives in `shared/culprit_model/`,
which `api/` also installs, so reaching for `networkx` here would make it
a *new* dependency of `api` — the one thing field 11 rules out. The
traversals below are breadth-first search over a graph D4 bounds at
"hundreds of nodes, not millions"; the standard library covers that
completely. `worker/app/correlation/graph.py` keeps its own `networkx`
usage untouched until Phase 32 removes it.
"""

from collections import deque
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.canonical import canonical_component
from culprit_model.subjects import SubjectKind
from culprit_model.subjects import build as build_subject


class ComponentKind(StrEnum):
    """What a component *is*, from Phase 27's field 7.

    A closed set on purpose. `kind` decides how a component can be
    probed (Phase 31) and what a divergence about it can mean, so a
    free-form string would push that decision to whoever typed the row.
    """

    SERVICE = "service"
    FRONTEND = "frontend"
    DATABASE = "database"
    QUEUE = "queue"
    EXTERNAL_API = "external_api"
    JOB = "job"
    CACHE = "cache"
    OBJECT_STORE = "object_store"


class ConnectionKind(StrEnum):
    """How one component reaches another. Also closed, and for the same
    reason: this is what selects a probe."""

    HTTP = "http"
    GRPC = "grpc"
    SQL = "sql"
    MESSAGE = "message"
    CACHE = "cache"
    DNS = "dns"
    AUTH = "auth"


class DeclaredBy(StrEnum):
    """Where a connection came from. Kept because "the machine noticed
    this" and "a human wrote this down" are different evidentiary
    weights, and a report that conflates them is lying by omission."""

    CULPRIT_YAML = "culprit_yaml"
    INFERRED = "inferred"
    ACCEPTED_SUGGESTION = "accepted_suggestion"


class Criticality(StrEnum):
    """Whether a connection carries a user request.

    `UNKNOWN` is a first-class value, not a placeholder to be cleaned up
    later. Phase 29 computes divergence severity from this, and the
    honest answer for a connection nobody has classified is "I do not
    know", not a guessed `BACKGROUND` that silently downgrades a real
    finding.
    """

    ON_REQUEST_PATH = "on_request_path"
    BACKGROUND = "background"
    UNKNOWN = "unknown"


class Component(BaseModel):
    """One node. `name` is canonicalised on the way in so that the same
    component named `Orders-SVC` in `culprit.yaml` and `orders-svc` in an
    OTel resource attribute is one node, not two."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: ComponentKind = ComponentKind.SERVICE
    #: Which environments this component exists in. Empty means "every
    #: environment" rather than "none" — the same convention
    #: `services.monitored_metrics` already uses (CLAUDE.md architecture
    #: point 8), so an unscoped component is the ordinary case.
    environment_scope: tuple[str, ...] = ()
    labels: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _canonical_name(cls, data: Any) -> Any:
        # `before`, not `after`: pydantic does not support an `after`
        # validator returning anything but `self`, and the model is
        # frozen so it cannot assign in place either. Canonicalising the
        # raw input is both supported and the more honest place for it —
        # the model is never briefly valid with a non-canonical name.
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            return {**data, "name": canonical_component(data["name"])}
        return data

    @property
    def subject(self) -> str:
        return build_subject(SubjectKind.COMPONENT, name=self.name)

    def exists_in(self, environment: str | None) -> bool:
        if not self.environment_scope or environment is None:
            return True
        return environment in self.environment_scope


class Connection(BaseModel):
    """One directed, typed edge.

    `contract_id` is nullable through Phase 27 by that phase's field 17 —
    connections may carry a null contract this phase, and Phase 28's
    extractors are what populate it.
    """

    model_config = ConfigDict(frozen=True)

    from_component: str
    to_component: str
    kind: ConnectionKind = ConnectionKind.HTTP
    contract_id: str | None = None
    declared_by: DeclaredBy = DeclaredBy.CULPRIT_YAML
    criticality: Criticality = Criticality.UNKNOWN

    @model_validator(mode="before")
    @classmethod
    def _canonical_endpoints(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        updated = dict(data)
        for field in ("from_component", "to_component"):
            if isinstance(updated.get(field), str):
                updated[field] = canonical_component(updated[field])
        return updated

    @model_validator(mode="after")
    def _no_self_loop(self) -> "Connection":
        if self.from_component == self.to_component:
            raise ValueError(f"a connection cannot loop back on {self.from_component!r}")
        return self

    @property
    def subject(self) -> str:
        return build_subject(
            SubjectKind.CONNECTION,
            from_component=self.from_component,
            to_component=self.to_component,
        )

    @property
    def key(self) -> tuple[str, str, ConnectionKind]:
        """The composite identity `connections` is unique on — two
        components may legitimately be connected in more than one way
        (Phase 27 field 8), e.g. HTTP *and* a shared cache."""
        return (self.from_component, self.to_component, self.kind)


class UnknownComponent(KeyError):
    """Raised rather than returning an empty path.

    An empty request path and "that component is not in the model" are
    different answers, and silently returning the former turns a typo
    into "nothing upstream could have caused this" — a false negative
    nobody investigates, which is the same failure mode
    `subjects.SubjectError` exists to prevent.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"no component named {name!r} in the model")


class SystemGraph(BaseModel):
    """A whole system model, in memory.

    Built once per request from `components`/`connections` rows and
    thrown away. Adjacency is materialised in the validator rather than
    recomputed per traversal, because a `GET /model/graph` on a
    branching topology walks the same edges repeatedly.
    """

    model_config = ConfigDict(frozen=True)

    components: tuple[Component, ...] = ()
    connections: tuple[Connection, ...] = ()

    @model_validator(mode="after")
    def _endpoints_exist(self) -> "SystemGraph":
        known = {component.name for component in self.components}
        dangling = sorted(
            {
                name
                for connection in self.connections
                for name in (connection.from_component, connection.to_component)
                if name not in known
            }
        )
        if dangling:
            raise ValueError(
                f"connection endpoint(s) not present as components: {dangling}. "
                "A connection to a component the model does not know about is a "
                "hole in the model, not an edge."
            )
        return self

    # --- lookups ------------------------------------------------------

    def component(self, name: str) -> Component:
        canonical = canonical_component(name)
        for candidate in self.components:
            if candidate.name == canonical:
                return candidate
        raise UnknownComponent(canonical)

    def outgoing(self, name: str) -> tuple[Connection, ...]:
        canonical = self.component(name).name
        return tuple(c for c in self.connections if c.from_component == canonical)

    def incoming(self, name: str) -> tuple[Connection, ...]:
        canonical = self.component(name).name
        return tuple(c for c in self.connections if c.to_component == canonical)

    # --- traversal ----------------------------------------------------

    def reachable_from(self, name: str) -> tuple[str, ...]:
        """Every component `name` can reach by following edges forward,
        excluding `name` itself unless a cycle genuinely returns to it.

        Breadth-first and cycle-safe: a mutual dependency
        (`a -> b -> a`, which `service_dependencies` stored for every
        declared pair) must terminate, not recurse.
        """
        return self._search(name, forward=True)

    def reaches(self, name: str) -> tuple[str, ...]:
        """The mirror of `reachable_from` — every component that can
        reach `name`. This is the set a symptom at `name` could have
        propagated *from*."""
        return self._search(name, forward=False)

    def _search(self, name: str, *, forward: bool) -> tuple[str, ...]:
        start = self.component(name).name
        seen: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            edges = self.outgoing(current) if forward else self.incoming(current)
            for edge in edges:
                nxt = edge.to_component if forward else edge.from_component
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return tuple(sorted(seen))

    def upstream_connections(self, symptom: str) -> tuple[Connection, ...]:
        """Phase 27's fourth acceptance criterion: *given a symptom
        component, the ordered set of upstream connections on its request
        path.*

        "Upstream" is in the direction of the dependency arrow: if
        `orders-svc -> payments-svc`, then a symptom observed at
        `orders-svc` may have come from `payments-svc`, so the connection
        `orders-svc -> payments-svc` is upstream of the symptom. The walk
        therefore follows edges *forward* from the symptom, collecting
        the connections it crosses.

        **Ordered by hop distance from the symptom**, nearest first, and
        within a hop by `(from, to, kind)` so the result is stable across
        runs — a report whose order changes between two identical runs is
        one an engineer cannot diff.

        Only connections that could carry a request are included:
        `Criticality.BACKGROUND` edges are excluded, because a nightly
        reconciliation job's link is not on the path a failing request
        took. `UNKNOWN` **is** included — see `Criticality`: an
        unclassified edge is not an absent one, and dropping it here
        would silently hide the real cause whenever nobody had got round
        to labelling the topology.
        """
        start = self.component(symptom).name
        ordered: list[Connection] = []
        seen_edges: set[tuple[str, str, ConnectionKind]] = set()
        visited: set[str] = {start}
        frontier = [start]

        while frontier:
            hop: list[Connection] = []
            for current in frontier:
                for edge in self.outgoing(current):
                    if edge.criticality is Criticality.BACKGROUND:
                        continue
                    if edge.key in seen_edges:
                        continue
                    seen_edges.add(edge.key)
                    hop.append(edge)
            hop.sort(key=lambda e: (e.from_component, e.to_component, str(e.kind)))
            ordered.extend(hop)

            frontier = []
            for edge in hop:
                if edge.to_component not in visited:
                    visited.add(edge.to_component)
                    frontier.append(edge.to_component)

        return tuple(ordered)

    def scoped_to(self, environment: str | None) -> "SystemGraph":
        """The subgraph that exists in one environment.

        A connection survives only if both its endpoints do — an edge
        with one leg in staging and one in production is not a half
        edge, it is not an edge.
        """
        if environment is None:
            return self
        kept = tuple(c for c in self.components if c.exists_in(environment))
        names = {component.name for component in kept}
        return SystemGraph(
            components=kept,
            connections=tuple(
                c
                for c in self.connections
                if c.from_component in names and c.to_component in names
            ),
        )
