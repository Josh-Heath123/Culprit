"""ProbeManifest and Reading — the OBSERVED plane's atomic units.

`docs/DIAGNOSTIC_PLAN.md` §2.6. A `Fact` is a claim about how something is
meant to be or is set up to be; a `Reading` is what happened when someone
actually went and measured, at a chosen point, at a known moment.

Pydantic for the same reason `facts.py` is: these cross a process boundary
(probe runner -> CLI -> API -> Postgres) and the validation *is* the
contract.

Four invariants are enforced here rather than left to the caller, each
because it has a silent-wrong-answer failure mode:

1. **`effect: mutate` cannot be constructed.** Not "is rejected by the
   loader" — the model itself refuses it, so a manifest that arrives by
   some path the loader does not guard still cannot produce a probe that
   writes. §2.6 says "no exceptions in this plan", and a rule enforced in
   one code path is a rule with one code path left to forget.
2. **`reason` is required when a verdict is `inconclusive` or `refused`.**
   A probe that cannot say *why* it could not answer is indistinguishable
   from one that guessed, which is the failure `.claude/rules/model.md`
   names directly. The `readings` CHECK constraint says the same thing in
   Postgres; this says it before the row is ever built.
3. **Evidence that is not marked redacted may not look like a credential.**
   Readings carry config names and shapes, never values (§2.2, and the
   rule in `.claude/rules/model.md`). A reading is the artefact most likely
   to be pasted into a bug report, because it is the one that describes a
   failure.
4. **Every capability named in `grants_used` must be a real one.** A
   reading that claims a grant nobody can spell is a reading whose
   provenance cannot be audited.

The `readings` table (migration `c07a5f31d8e4`) already carries every
field below; Phase 31 populates it for the first time.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from culprit_model.capabilities import Capability
from culprit_model.facts import Provenance
from culprit_model.planes import Plane
from culprit_model.redaction import looks_like_credential, redact_credentials
from culprit_model.subjects import SubjectError
from culprit_model.subjects import parse as parse_subject

#: The hypothesis kinds a probe can discriminate — what the isolation walk
#: chooses probes by (Phase 32). The Go half is model.HypothesisKinds;
#: shared/tests/investigation_conformance.json holds the two to one list.
HYPOTHESIS_KINDS: frozenset[str] = frozenset(
    {
        "component_fails",
        "connection_unreachable",
        "database_unreachable",
        "tls_invalid",
        "auth_audience_mismatch",
        "auth_rejected",
        "contract_mismatch",
        "config_missing",
    }
)


class Verdict(StrEnum):
    """Four verdicts, not two (§2.6).

    `INCONCLUSIVE` means the probe ran and could not establish the answer.
    `REFUSED` means the capability was not granted. Both are honest
    outputs and both appear in reports — "I could not check X because you
    have not granted Y" is a feature, not an error.
    """

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    REFUSED = "refused"

    @property
    def needs_reason(self) -> bool:
        return self in (Verdict.INCONCLUSIVE, Verdict.REFUSED)


class Effect(StrEnum):
    """What running a probe does to the system under test.

    `MUTATE` is named so it can be *refused* by name rather than falling
    through as an unrecognised string. See `ProbeManifest`.
    """

    INSPECT = "inspect"
    OBSERVE = "observe"
    INTERROGATE = "interrogate"
    MUTATE = "mutate"


class Cost(StrEnum):
    CHEAP = "cheap"
    METERED = "metered"
    INTRUSIVE = "intrusive"


class Evidence(BaseModel):
    """One piece of what the probe saw, kept so a human can check it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    value: str
    redacted: bool = False

    @model_validator(mode="after")
    def _unredacted_evidence_is_not_credential_shaped(self) -> "Evidence":
        if not self.redacted and looks_like_credential(self.value):
            raise ValueError(
                f"evidence of kind {self.kind!r} is credential-shaped but is "
                "not marked redacted. A reading is the artefact most likely "
                "to be pasted into a bug report; set redacted=True and "
                "replace the value with a description of it."
            )
        return self


class Produces(BaseModel):
    """A (subject_template, predicate) pair this probe can report on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_template: str
    predicate: str


class ProbeManifest(BaseModel):
    """§2.6. Manifests are data, not code, so the catalogue is extensible
    without recompiling the engine (Phase 31 field 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int = Field(ge=1)
    effect: Effect
    capabilities: tuple[Capability, ...] = ()
    #: A JSON Schema object describing this probe's inputs. Free-form by
    #: necessity — it is a schema, not a value — but never carries a
    #: literal, because it describes shapes.
    inputs: dict = Field(default_factory=dict)
    timeout_ms: int = Field(gt=0, le=300_000)
    #: Which plane supplies the expectation this probe measures against,
    #: or None for a probe that reports a measurement with no expectation.
    expected_from: Plane | None = None
    produces: tuple[Produces, ...] = ()
    #: Hypothesis ids a result rules out. Populated by Phase 32; an empty
    #: tuple here means "discriminates nothing yet", not "discriminates
    #: nothing ever".
    discriminates: tuple[str, ...] = ()
    cost: Cost = Cost.CHEAP

    @model_validator(mode="after")
    def _no_probe_may_mutate(self) -> "ProbeManifest":
        if self.effect is Effect.MUTATE:
            raise ValueError(
                f"probe {self.id!r} declares effect: mutate. No probe in this "
                "plan may mutate the system under test, and no *.write "
                "capability exists to permit it (§2.6, §2.7). Adding one is a "
                "design decision requiring its own plan document, not a probe."
            )
        return self

    @model_validator(mode="after")
    def _expected_from_is_not_observed(self) -> "ProbeManifest":
        if self.expected_from is Plane.OBSERVED:
            raise ValueError(
                f"probe {self.id!r} declares expected_from: OBSERVED. A "
                "reading cannot be its own expectation — that is the "
                "baseline-as-truth mistake the three-plane model exists to "
                "prevent. Use INTENT, CONFIGURED, or none."
            )
        return self

    @model_validator(mode="after")
    def _discriminates_only_known_kinds(self) -> "ProbeManifest":
        unknown = sorted(set(self.discriminates) - HYPOTHESIS_KINDS)
        if unknown:
            raise ValueError(
                f"probe {self.id!r} discriminates {unknown}, which the isolation "
                "walk does not know; it would never be chosen, silently"
            )
        return self

    @model_validator(mode="after")
    def _id_is_well_formed(self) -> "ProbeManifest":
        parts = self.id.split(".")
        if len(parts) != 3 or parts[0] != "probe" or not all(parts):
            raise ValueError(
                f"probe id {self.id!r} must be 'probe.<group>.<name>', e.g. 'probe.net.tcp_connect'"
            )
        return self


class Reading(BaseModel):
    """§2.6. One measurement, taken at one point, at one moment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    probe_id: str
    probe_version: int = Field(ge=1)
    #: A subject URI (§2.3), built by `subjects.build` — never formatted
    #: by hand.
    target: str
    environment: str
    verdict: Verdict
    measured: dict = Field(default_factory=dict)
    expected: dict | None = None
    expected_source: Provenance | None = None
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = None
    taken_at: datetime
    expires_at: datetime | None = None
    agent_id: str
    grants_used: tuple[Capability, ...] = ()

    @model_validator(mode="after")
    def _unresolved_verdict_needs_a_reason(self) -> "Reading":
        if self.verdict.needs_reason and not (self.reason or "").strip():
            raise ValueError(
                f"a {self.verdict.value} reading from {self.probe_id!r} must "
                "give a reason. A probe that cannot say why it could not "
                "answer is a probe that guesses."
            )
        return self

    @model_validator(mode="after")
    def _target_is_a_real_subject(self) -> "Reading":
        try:
            parse_subject(self.target)
        except SubjectError as exc:
            raise ValueError(
                f"reading target {self.target!r} is not a subject URI: {exc}. "
                "Build it with subjects.build(), never by string formatting."
            ) from exc
        return self

    @model_validator(mode="after")
    def _expiry_follows_measurement(self) -> "Reading":
        if self.expires_at is not None and self.expires_at < self.taken_at:
            raise ValueError(f"reading from {self.probe_id!r} expires before it was taken")
        return self

    @model_validator(mode="after")
    def _a_refusal_names_no_grant_it_used(self) -> "Reading":
        if self.verdict is Verdict.REFUSED and self.grants_used:
            raise ValueError(
                f"a refused reading from {self.probe_id!r} lists grants_used "
                f"{[g.value for g in self.grants_used]}. Refused means the "
                "capability was not granted, so nothing was used."
            )
        return self


def redact_reading(reading: Reading) -> Reading:
    """Return a copy of `reading` with free text passed through redaction.

    The Python half of `model.RedactReading` in Go, and applied for a
    different reason. The CLI redacts before a Reading exists as a value,
    so its own output is safe by construction. This exists because
    `POST /readings` accepts readings from *outside* that guarantee — a
    third-party probe, an older `culprit` binary, a hand-written payload
    — and what it accepts lands in a 90-day hypertable that `api-reader`
    can read.

    A transformation rather than a rejection, deliberately: `evidence`
    already refuses credential-shaped text at construction because a
    probe builds it locally and can be held to a standard, whereas
    `measured` and `reason` legitimately carry a caller's URL, and
    refusing the whole batch would lose every honest reading alongside
    the careless one.
    """
    return reading.model_copy(
        update={
            "reason": _redacted(reading.reason),
            "measured": _redact_mapping(reading.measured),
            "expected": _redact_mapping(reading.expected),
            "evidence": tuple(
                item
                if item.redacted
                else item.model_copy(update={"value": redact_credentials(item.value)})
                for item in reading.evidence
            ),
        }
    )


def _redacted(text: str | None) -> str | None:
    return redact_credentials(text) if text else text


def _redact_mapping(values: dict | None) -> dict | None:
    """Redact string values, walking nested objects and arrays.

    Only strings are rewritten: a number cannot carry a credential, and
    stringifying one would change the stored shape to no purpose.
    """
    if values is None:
        return None
    redacted: dict = {}
    for key, value in values.items():
        if isinstance(value, str):
            redacted[key] = redact_credentials(value)
        elif isinstance(value, dict):
            redacted[key] = _redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_credentials(item) if isinstance(item, str) else item for item in value
            ]
        else:
            redacted[key] = value
    return redacted
