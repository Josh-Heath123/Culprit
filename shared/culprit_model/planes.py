"""Planes, provenance source kinds and intent confidence ranks.

docs/DIAGNOSTIC_PLAN.md §2.1 and §2.4. Three planes, not four: a
historical baseline is a *statistic over* OBSERVED and is deliberately
never a plane of its own (§2 decision register — treating "usual" as a
proxy for "correct" is the mistake this model exists to avoid).
"""

from enum import IntEnum, StrEnum


class Plane(StrEnum):
    """What kind of claim a Fact is.

    INTENT      — what the system is supposed to do. Environment-independent
                  by definition, which is why `intent_facts` has no
                  `environment` column at all.
    CONFIGURED  — what a specific environment is set up to do.
    OBSERVED    — what actually happened in a specific environment.
    """

    INTENT = "INTENT"
    CONFIGURED = "CONFIGURED"
    OBSERVED = "OBSERVED"

    @property
    def requires_environment(self) -> bool:
        return self is not Plane.INTENT


class SourceKind(StrEnum):
    """How a Fact was come by (§2.2's Provenance.source_kind)."""

    SPEC = "spec"
    INTROSPECTION = "introspection"
    STATIC = "static"
    TEST = "test"
    ASSERTION = "assertion"
    OBSERVATION = "observation"


class ConfidenceRank(IntEnum):
    """§2.4. Orders reports and picks comparison defaults.

    Rank never silently discards a source: two INTENT facts with the same
    subject+predicate and different values are an `intent_conflict`
    divergence (§0.3), not a contest the higher rank quietly wins. The
    rank only decides which one is *presented* first.

    An int, not a StrEnum, so `>` means what it looks like. Extractors may
    emit any int in 0..100 — these are the named landmarks from the plan,
    not an exhaustive set.
    """

    DEVELOPER_ASSERTION = 100
    RUNTIME_INTROSPECTION = 90
    COMMITTED_SPEC = 80
    STATIC_FRAMEWORK_CODE = 60
    STATIC_TESTS = 50
    STATIC_CLIENT_CALL_SITES = 40
    OBSERVED_TRAFFIC = 20
