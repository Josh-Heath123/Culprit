"""Pure connected-components graph logic for correlating anomalies into
incident candidates.

No DB, no Redis, no arq — mirrors the pure/impure split already
established in app/anomaly (scorer.py pure, state.py/job.py do I/O).
Deterministic, rule-based graph construction only; no LLM involved
anywhere in this phase. Per CLAUDE.md, a wrong automated correlation
here is the failure mode that makes the whole product untrustworthy, so
this stays testable and deterministic, not a judgment call.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import networkx as nx

#: How close in time two anomalies must be to even be considered
#: possibly related. A named config value, not a literal buried in the
#: edge-building loop.
CORRELATION_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class AnomalyNode:
    id: UUID
    service_name: str
    detected_at: datetime


def _services_related(a: str, b: str, adjacency: Mapping[str, frozenset[str]]) -> bool:
    return a == b or b in adjacency.get(a, frozenset())


def _within_window(a: datetime, b: datetime) -> bool:
    return abs(a - b) <= CORRELATION_WINDOW


def build_graph(nodes: list[AnomalyNode], adjacency: Mapping[str, frozenset[str]]) -> nx.Graph:
    """One node per anomaly. An edge requires BOTH time proximity and
    service adjacency — time proximity alone is deliberately not
    sufficient. Two unrelated services having a coincidental anomaly at
    the same moment must not get an edge just because they're close in
    time; that's the actual point of the adjacency condition, not an
    incidental restriction.

    `adjacency` is a parameter, not an import (Phase 14) — this module
    stays pure and DB-free (no import of shared/culprit_shared/services.py
    or anything worker/app/correlation/job.py-shaped); the caller loads
    the real adjacency from the services/service_dependencies tables and
    passes it in. Expected symmetric: if b is reachable from a, the
    caller must also have inserted a into adjacency[b] — this function
    doesn't infer the reverse direction itself.
    """
    graph: nx.Graph = nx.Graph()
    for node in nodes:
        graph.add_node(node.id)

    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if _within_window(a.detected_at, b.detected_at) and _services_related(
                a.service_name, b.service_name, adjacency
            ):
                graph.add_edge(a.id, b.id)

    return graph


def connected_components(graph: nx.Graph) -> list[set[UUID]]:
    return [set(component) for component in nx.connected_components(graph)]
