"""The three-plane core model (docs/DIAGNOSTIC_PLAN.md §2).

Phase 26 lands this package alongside the existing pipeline without
changing any of its behaviour: nothing in `api/` or `worker/` populates
the new tables yet (that phase's field 17). It exists so Phase 27
onwards has one definition of a plane, a Fact, a subject URI and a
Divergence to build against, rather than each layer inventing its own.

Shipped inside the same `culprit-shared` distribution as
`culprit_shared/` — one path dependency, already wired into both
`api/pyproject.toml` and `worker/pyproject.toml`, rather than a second
one that would have to be added to three lockfiles to say the same
thing. The two packages stay separate imports because they answer
different questions: `culprit_shared` is the *wire* shape of telemetry
in flight, `culprit_model` is the *semantic* shape of what we claim to
be true.

Deterministic by construction — see `.claude/rules/determinism.md`. No
module here may import an LLM or embedding client;
`scripts/check_no_llm_imports.py` asserts that structurally in CI.
"""

from culprit_model.canonical import (
    canonical_component,
    canonical_identifier,
    canonical_json,
    canonical_method,
    canonical_path,
    canonical_value,
    values_equal,
)
from culprit_model.facts import (
    Divergence,
    DivergenceKind,
    DivergenceStatus,
    Fact,
    Provenance,
    Severity,
)
from culprit_model.graph import (
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    Criticality,
    DeclaredBy,
    SystemGraph,
    UnknownComponent,
)
from culprit_model.planes import ConfidenceRank, Plane, SourceKind
from culprit_model.subjects import SubjectKind, build, parse

__all__ = [
    "Component",
    "ComponentKind",
    "ConfidenceRank",
    "Connection",
    "ConnectionKind",
    "Criticality",
    "DeclaredBy",
    "Divergence",
    "DivergenceKind",
    "DivergenceStatus",
    "Fact",
    "Plane",
    "Provenance",
    "Severity",
    "SourceKind",
    "SubjectKind",
    "SystemGraph",
    "UnknownComponent",
    "build",
    "canonical_component",
    "canonical_identifier",
    "canonical_json",
    "canonical_method",
    "canonical_path",
    "canonical_value",
    "parse",
    "values_equal",
]
