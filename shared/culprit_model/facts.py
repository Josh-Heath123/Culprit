"""Fact, Provenance and Divergence — the atomic units of the model.

docs/DIAGNOSTIC_PLAN.md §2.2 and §2.5. Pydantic models rather than plain
dataclasses for the same reason `culprit_shared/raw_event.py` is: these
cross a process boundary (extractor subprocess -> CLI -> API -> Postgres)
and the validation is the contract, not decoration on top of it.

Three invariants are enforced here rather than left to the caller,
because each has a silent-wrong-answer failure mode:

1. An INTENT fact may not carry an environment, and a CONFIGURED or
   OBSERVED fact must (§0.2 — INTENT is what the system is *supposed* to
   do, which is environment-independent by definition). The schema
   encodes the same rule: `intent_facts` has no `environment` column.
2. A Divergence's two sides must be about the same subject+predicate.
   A divergence between two unrelated facts is not a weaker finding, it
   is a meaningless one.
3. **A fact about a config key cannot carry a literal value** unless it
   names the explicit per-key grant that permitted it (§2.2, Phase 28
   field 4). This used to live only in a Postgres CHECK constraint,
   which left the artefact the promise is actually about — a capture
   bundle serialised to JSON and attached to a bug report — completely
   unguarded. It is enforced here now, so `model_dump_json()` on a
   bundle that never touches a database is safe by construction. See
   `shape.py` for the other half.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.canonical import canonical_value
from culprit_model.planes import Plane, SourceKind
from culprit_model.shape import ValueShape
from culprit_model.subjects import SubjectError, SubjectKind
from culprit_model.subjects import build as build_subject
from culprit_model.subjects import parse as parse_subject


class Provenance(BaseModel):
    """Where a Fact came from, precisely enough to go and look.

    `artefact` and `locator` are what turn a report line into something a
    developer can open: "openapi.json" plus "$.paths./orders.post", or
    "api/app/main.py" plus "L142".
    """

    model_config = ConfigDict(frozen=True)

    source_kind: SourceKind
    extractor: str
    artefact: str | None = None
    locator: str | None = None
    #: §2.4's ranks are the named landmarks, not a closed set — an
    #: extractor may report any 0..100. Only meaningful for INTENT facts;
    #: CONFIGURED/OBSERVED are readings of a real system rather than
    #: claims about what it should be, which is why `configured_facts`
    #: has no such column.
    confidence_rank: int = Field(ge=0, le=100)


class Fact(BaseModel):
    """A single claim, on one plane, about one subject.

    `extra="forbid"`, not for tidiness: an open model is a place a
    literal config value can be smuggled past `_config_values_need_a_grant`
    below by giving it a field name that validator has never heard of.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plane: Plane
    subject: str
    predicate: str
    value: Any = None
    #: Set instead of `value` for a config key (§2.2). A closed type, so
    #: it has no field a literal can go in — see `shape.ValueShape`.
    value_shape: ValueShape | None = None
    #: Names the explicit per-key capability grant that permitted a
    #: literal `value` on a `config:` subject. Mirrors
    #: `configured_facts.grant_ref`; an empty string is not a grant.
    grant_ref: str | None = None
    environment: str | None = None
    provenance: Provenance
    captured_at: datetime
    capture_id: UUID

    @model_validator(mode="after")
    def _config_values_need_a_grant(self) -> "Fact":
        """Phase 28 acceptance criterion 3, in the one place that can
        actually hold the line.

        A `config:` subject means this fact is about a key whose value is
        a credential far more often than not. Carrying that value is
        allowed only when `grant_ref` names the grant that permitted it —
        the same rule as `ck_configured_facts_value_requires_grant`, moved
        up into the type so it also applies to a bundle that is written
        to a file and emailed rather than inserted.

        **The one exception, and why it is safe.** A `bool` is allowed
        without a grant. Extractors need to assert things *about* a key
        that are not its value — `read_by: true`, `required: true`,
        `exists: true` — and a boolean has exactly two inhabitants, so it
        cannot carry a credential, a hostname, or anything else worth
        redacting. Every other type is refused: a string, a number, a
        list and a mapping can all hold a secret, and a numeric API key
        is a real thing. The line is drawn at "can this type hold
        information about the value" rather than at "does this
        particular value look sensitive", because the second is a
        judgement call and this has to be a rule.

        **The subject must be canonical, and that is load-bearing.** An
        earlier version returned early when the subject did not parse, on
        the reasoning that `subjects.build()` owns that error. It does
        not, here: a Fact arriving over the wire has never been through
        `build()` — the extractor protocol carries a plain string, and
        extractors are third-party subprocesses. So a subject that merely
        *looks* like a config subject without being one slipped past this
        check entirely, and past the database's too, because
        `ck_intent_facts_value_requires_grant` keys off an anchored,
        case-sensitive LIKE on the config scheme. Both layers opened at
        once: an upper-cased scheme, and a scheme with a leading space,
        both stored an ungranted DATABASE_URL.

        Demonstrated end to end by the Phase 28 invariant audit, against
        a real database under the real role.

        Requiring the round trip — `build(parse(s)) == s` — closes it and
        restores §2.3's actual guarantee at the one boundary where a
        subject enters the system without being built here. It costs
        nothing: every subject `build()` produces round-trips by
        construction, which is a property the conformance fixture already
        asserts.
        """
        try:
            kind, parts = parse_subject(self.subject)
            canonical = build_subject(kind, **parts)
        except SubjectError as exc:
            # **The subject is not echoed, and that is not fussiness.** It
            # is attacker-controlled text on this path, and a subject is
            # exactly where somebody would hide a value —
            # `opaque:postgresql://u:hunter2@db/orders` parses as an
            # unknown scheme, and an error quoting it would put the DSN
            # in the 422 body and the access log. pydantic's own `loc`
            # already says which fact failed, which is what a caller
            # needs. Caught by a test that posted precisely that.
            raise ValueError(
                "subject is not a valid subject URI. Build subjects with "
                "culprit_model.subjects.build() — see docs/DIAGNOSTIC_PLAN.md §2.3."
            ) from exc
        if canonical != self.subject:
            # Neither side is echoed: the canonical form is derived from
            # the input, so printing it leaks the input.
            raise ValueError(
                "subject is not in canonical form. Two sources describing the same "
                "thing must produce a byte-identical subject or nothing is ever "
                "compared, and a subject that only looks canonical also slips past "
                "the checks keyed on its scheme. Build it with "
                "culprit_model.subjects.build()."
            )
        if kind is not SubjectKind.CONFIG:
            if self.value_shape is not None:
                raise ValueError(
                    f"value_shape is only meaningful for a config: subject "
                    f"(got {self.subject!r})"
                )
            return self
        if (
            self.value is not None
            and not isinstance(self.value, bool)
            and not (self.grant_ref or "").strip()
        ):
            raise ValueError(
                f"a fact about config key {self.subject!r} may not carry a literal "
                f"{type(self.value).__name__} value without a grant_ref naming the "
                "per-key grant that permitted it — put the classification in "
                "value_shape instead (docs/DIAGNOSTIC_PLAN.md §2.2). Only a bool "
                "is allowed ungranted, for assertions about a key rather than its "
                "value."
            )
        return self

    @model_validator(mode="after")
    def _environment_matches_plane(self) -> "Fact":
        if self.plane.requires_environment and not self.environment:
            raise ValueError(f"a {self.plane} fact requires an environment")
        if not self.plane.requires_environment and self.environment:
            raise ValueError(
                f"a {self.plane} fact must not carry an environment "
                f"(got {self.environment!r}) — INTENT is environment-independent"
            )
        return self

    @property
    def canonical(self) -> Any:
        """The value as comparison sees it (`canonical.canonical_value`)."""
        return canonical_value(self.value)


class DivergenceKind(StrEnum):
    """§2.5. `INTENT_CONFLICT` is the one worth reading twice: two INTENT
    sources disagreeing is a finding in its own right (§0.3), not
    something a confidence rank silently resolves by picking a winner.

    `BASELINE_DEVIATION` compares OBSERVED against a statistic derived
    from OBSERVED — it is emphatically not a fourth plane (§2 decisions
    register), which is why it is a divergence *kind* and nothing more.
    """

    INTENT_CONFLICT = "intent_conflict"
    INTENT_VS_CONFIGURED = "intent_vs_configured"
    INTENT_VS_OBSERVED = "intent_vs_observed"
    CONFIGURED_VS_OBSERVED = "configured_vs_observed"
    ENV_VS_ENV = "env_vs_env"
    BASELINE_DEVIATION = "baseline_deviation"


class Severity(StrEnum):
    """Computed deterministically from the system model (§2.5), never an
    LLM judgement: a divergence on a subject that lies on a known request
    path is `BREAKS_REQUEST_PATH`; one on an unreferenced config key is
    `COSMETIC`. `UNKNOWN` is honest and expected until Phase 27's system
    model exists to rank against.
    """

    BREAKS_REQUEST_PATH = "breaks_request_path"
    DEGRADES = "degrades"
    COSMETIC = "cosmetic"
    UNKNOWN = "unknown"


class DivergenceStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class Divergence(BaseModel):
    """Two facts about the same subject+predicate that disagree."""

    model_config = ConfigDict(frozen=True)

    id: UUID | None = None
    kind: DivergenceKind
    subject: str
    predicate: str
    left: Fact
    right: Fact
    severity: Severity = Severity.UNKNOWN
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    status: DivergenceStatus = DivergenceStatus.OPEN
    #: One sentence a human reads first, built from the two facts by the
    #: comparator. Never generated: D8 forbids an LLM on this path.
    explanation: str = ""
    #: Why that severity, in the system model's own terms. A severity
    #: nobody can trace is a severity nobody trusts.
    severity_reason: str = ""
    #: The reason from `culprit.yaml` that silenced this, when it is
    #: suppressed. A suppressed finding still has to explain itself, or
    #: the suppression list stops being auditable.
    suppressed_by: str = ""

    @model_validator(mode="after")
    def _sides_are_comparable(self) -> "Divergence":
        if self.left.subject != self.right.subject:
            raise ValueError(
                f"divergence sides disagree on subject: "
                f"{self.left.subject!r} vs {self.right.subject!r}"
            )
        if self.left.predicate != self.right.predicate:
            raise ValueError(
                f"divergence sides disagree on predicate: "
                f"{self.left.predicate!r} vs {self.right.predicate!r}"
            )
        if self.subject != self.left.subject or self.predicate != self.left.predicate:
            raise ValueError("divergence subject/predicate must match its own facts")
        return self

    def identity(self) -> str:
        """A stable key for one finding, across runs.

        Derived from what the finding *is* - its subject, its predicate,
        and the two *sources* that disagreed - so the same unfixed fault
        carries the same key on Tuesday and on Friday, and a consumer can
        tell "still broken" from "broken again".

        A source is an extractor **and** an artefact. One extractor
        legitimately reads several independent descriptions of the same
        thing - the ORM's columns and the migration chain's columns come
        from the same process - so keying on the extractor alone made two
        genuinely different findings share one key, and the second upsert
        silently overwrote the first.

        Deliberately not a hash of the whole object: values move, clocks
        move, severities move when the system model changes. Identity
        does not.

        **Kept byte-identical to `Divergence.ID()` in
        `cli/internal/model/divergence.go`**, which is what the CLI
        computes before it ever reaches this model. The two are held
        together by `shared/tests/test_divergence_identity.py`, reading
        the same fixture the Go test reads - the same arrangement subject
        URIs use, and for the same reason: two implementations of one
        identity that drift apart produce duplicate history nobody
        notices.
        """
        parts = [
            self.subject,
            self.predicate,
            self.left.provenance.extractor,
            self.left.provenance.artefact or "",
            self.right.provenance.extractor,
            self.right.provenance.artefact or "",
        ]
        # Phase 30: a source is also *where* it read from. "Staging lacks
        # DATABASE_URL" and "production lacks DATABASE_URL" differ only
        # in environment, and would otherwise share a key and overwrite
        # each other on upload. Appended only when either side has one,
        # so every INTENT-only identity already stored is unchanged.
        if self.left.environment or self.right.environment:
            parts += [self.left.environment or "", self.right.environment or ""]
        return "|".join(parts)
