"""Verification — Phase 34: whether a change fixed what an investigation found.

The Python half of `cli/internal/model/verification.go`, held to it by
`shared/tests/verification_conformance.json`. `culprit verify` builds one;
the control plane stores it from Phase 34 part 2.

A verification is its own append-only record pointing at an investigation.
The investigation is never edited: whether it is verified is derived from
its latest verification ("How Phase 34 is run", 2026-11-10).

**The verdict is a pure function of the record.** It holds every reading
re-run (twice), the changes named, whether there is a capture of the
environment before and after, and the differences between the two.
`judge()` computes the verdict and the three clause flags from that, and
the model refuses a record whose verdict or flags say anything else. So a
`verified` verification cannot be constructed unless all three clauses
hold:

1. every reading that failed passes, on both runs;
2. every reading that passed still passes;
3. every difference between the environment before and after is explained
   by a change named — which needs a change named and a capture before.

Naive verification — re-running the failing probe once — is confidence
theatre: caching, intermittency and an unrelated change all produce a pass.
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from culprit_model.readings import Reading, Verdict
from culprit_model.subjects import SubjectError, SubjectKind
from culprit_model.subjects import parse as parse_subject


class VerificationVerdict(StrEnum):
    #: all three clauses hold.
    VERIFIED = "verified"
    #: a reading that failed still fails.
    NOT_RESOLVED = "not_resolved"
    #: the failing readings pass, but one that passed now fails.
    REGRESSED = "regressed"
    #: the failing readings pass, but the environment changed in a way the
    #: named change does not explain.
    CHANGED_UNDERNEATH = "changed_underneath"
    #: anything else: a probe refused or inconclusive now, a result that
    #: flips between the two runs, no change named, no record of before.
    INCONCLUSIVE = "inconclusive"


class ChangeKind(StrEnum):
    IMAGE = "image"
    CONFIG = "config"
    COMMIT = "commit"
    #: a fix that is none of the others — a firewall rule removed, a flag
    #: cleared, a service restarted — described in words (Q20).
    ACTION = "action"


_COMMIT_REF = re.compile(r"^[0-9a-f]{7,40}$")

#: The longest an action's description may be, in characters.
MAX_ACTION_DESCRIPTION = 500

#: A name that is not blank: Go trims before it checks, and so does this.
Named = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _parsed(subject: str) -> tuple[SubjectKind, dict[str, str]] | None:
    try:
        return parse_subject(subject)
    except SubjectError:
        return None


def _article(kind: ChangeKind) -> str:
    if kind in (ChangeKind.IMAGE, ChangeKind.ACTION):
        return f"an {kind.value}"
    return f"a {kind.value}"


class Change(BaseModel):
    """What was applied: an image for a component, a config key for a
    component, a commit, or an action described in words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ChangeKind
    #: `image:<component>` or `config:<component>/<key>`.
    subject: str | None = None
    #: a commit id, 7 to 40 lowercase hex characters.
    ref: str | None = None
    #: what an action did, in words.
    description: str | None = None

    @field_validator("subject", "ref", "description", mode="before")
    @classmethod
    def _empty_is_absent(cls, value: object) -> object:
        # Go writes an absent subject or ref as nothing, and reads "" as
        # absent: the two models must accept the same records.
        return None if value == "" else value

    @model_validator(mode="after")
    def _names_one_thing_of_its_kind(self) -> "Change":
        if self.kind is ChangeKind.ACTION:
            if self.subject is not None or self.ref is not None:
                raise ValueError("an action change is described in words, with no subject or ref")
            described = (self.description or "").strip()
            if not described:
                raise ValueError("an action change says what was done")
            if len(described) > MAX_ACTION_DESCRIPTION:
                raise ValueError(
                    f"an action's description is {len(described)} characters; "
                    f"at most {MAX_ACTION_DESCRIPTION}"
                )
            return self
        if self.description is not None:
            raise ValueError(
                f"{_article(self.kind)} change names what was applied; "
                "only an action is described in words"
            )
        if self.kind is ChangeKind.COMMIT:
            if self.subject is not None:
                raise ValueError("a commit change names a ref, not a subject")
            if not _COMMIT_REF.match(self.ref or ""):
                raise ValueError(
                    f"commit ref {self.ref!r} is not a commit id (7-40 hex characters)"
                )
            return self
        if self.ref is not None:
            raise ValueError(f"{_article(self.kind)} change names a subject, not a ref")
        parsed = _parsed(self.subject or "")
        want = SubjectKind.IMAGE if self.kind is ChangeKind.IMAGE else SubjectKind.CONFIG
        if parsed is None or parsed[0] is not want:
            raise ValueError(
                f"{_article(self.kind)} change names a {want.value}: subject, got {self.subject!r}"
            )
        return self

    @property
    def label(self) -> str:
        """How a difference cites the change that explains it."""
        if self.kind is ChangeKind.COMMIT:
            return f"commit:{self.ref}"
        if self.kind is ChangeKind.ACTION:
            return f"action: {(self.description or '').strip()}"
        return str(self.subject)

    def touches(self, subject: str) -> bool:
        """Whether a difference on `subject` is one this change explains.

        A config key explains that key. An image explains that component's
        image and its packages, which ship in it. A commit or an action
        explains nothing a capture records: captures hold neither.
        """
        if self.kind in (ChangeKind.COMMIT, ChangeKind.ACTION):
            return False
        if self.kind is ChangeKind.CONFIG:
            return subject == self.subject
        changed = _parsed(str(self.subject))
        target = _parsed(subject)
        if changed is None or target is None:
            return False
        return target[0] in (SubjectKind.IMAGE, SubjectKind.DEP) and (
            target[1].get("component") == changed[1].get("component")
        )


class Rerun(BaseModel):
    """One of the investigation's readings, measured again twice, in the
    environment it was first taken in — a counterfactual reading in a
    reference environment is re-run there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reading_id: Named
    #: the verdict the investigation recorded.
    was: Verdict
    probe_id: Named
    target: str
    environment: Named
    runs: tuple[Reading, Reading]

    @model_validator(mode="after")
    def _the_runs_repeat_the_reading(self) -> "Rerun":
        for run in self.runs:
            if (run.probe_id, run.target, run.environment) != (
                self.probe_id,
                self.target,
                self.environment,
            ):
                raise ValueError(
                    f"a re-run of {self.reading_id} measured {run.probe_id} on {run.target} in "
                    f"{run.environment}, not {self.probe_id} on {self.target} in {self.environment}"
                )
        return self

    @property
    def now(self) -> Verdict | None:
        """The verdict both runs agree on, if it is pass or fail; None for
        a flip, a refusal or an inconclusive run."""
        first, second = self.runs[0].verdict, self.runs[1].verdict
        if first == second and first in (Verdict.PASS, Verdict.FAIL):
            return first
        return None


class Difference(BaseModel):
    """One question the capture before and the capture after answer
    differently. Subject and predicate only: never a value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    predicate: Named
    #: the label of the first named change that touches the subject, or
    #: None when none does.
    explained_by: str | None = None

    @field_validator("subject")
    @classmethod
    def _subject_is_a_subject(cls, value: str) -> str:
        try:
            parse_subject(value)
        except SubjectError as exc:
            raise ValueError(f"difference subject {value!r} is not a subject URI: {exc}") from exc
        return value


class Judgement(BaseModel):
    model_config = ConfigDict(frozen=True)

    failing_now_passes: bool
    no_regressions: bool
    changes_explained: bool
    verdict: VerificationVerdict


def judge(
    reran: tuple[Rerun, ...],
    applied_change: tuple[Change, ...],
    before_capture: str | None,
    after_capture: str | None,
    differences: tuple[Difference, ...],
) -> Judgement:
    """The verdict rules, in order. Go's model.Judge is the same function."""
    failed = [r for r in reran if r.was is Verdict.FAIL]
    passed = [r for r in reran if r.was is Verdict.PASS]
    failing_now_passes = bool(failed) and all(r.now is Verdict.PASS for r in failed)
    no_regressions = all(r.now is Verdict.PASS for r in passed)
    changes_explained = (
        bool(applied_change)
        and before_capture is not None
        and after_capture is not None
        and all(d.explained_by is not None for d in differences)
    )

    if any(r.now is Verdict.FAIL for r in failed):
        verdict = VerificationVerdict.NOT_RESOLVED
    elif failing_now_passes and any(r.now is Verdict.FAIL for r in passed):
        verdict = VerificationVerdict.REGRESSED
    elif not failing_now_passes or not no_regressions:
        verdict = VerificationVerdict.INCONCLUSIVE
    elif any(r.now is not Verdict.PASS for r in reran):
        # a reading the investigation could not answer is unanswered now,
        # or now fails: either way the path is not shown clear.
        verdict = VerificationVerdict.INCONCLUSIVE
    elif not applied_change or before_capture is None or after_capture is None:
        verdict = VerificationVerdict.INCONCLUSIVE
    elif not changes_explained:
        verdict = VerificationVerdict.CHANGED_UNDERNEATH
    else:
        verdict = VerificationVerdict.VERIFIED
    return Judgement(
        failing_now_passes=failing_now_passes,
        no_regressions=no_regressions,
        changes_explained=changes_explained,
        verdict=verdict,
    )


class Verification(BaseModel):
    """Phase 34 field 7, as decided 2026-11-10."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Named
    investigation_id: Named
    environment: Named
    applied_change: tuple[Change, ...] = ()
    reran: tuple[Rerun, ...] = Field(min_length=1)
    #: the capture id of the environment as `culprit diagnose` found it,
    #: or None when the investigation has no record of before.
    before_capture: str | None = None
    after_capture: str | None = None
    differences: tuple[Difference, ...] = ()
    failing_now_passes: bool
    no_regressions: bool
    changes_explained: bool
    verdict: VerificationVerdict
    reason: str = Field(min_length=1)
    verified_at: datetime

    @model_validator(mode="after")
    def _the_record_supports_the_verdict(self) -> "Verification":
        if not self.reason.strip():
            raise ValueError("a verification gives no reason for its verdict")
        ids = [r.reading_id for r in self.reran]
        if len(ids) != len(set(ids)):
            raise ValueError(f"verification {self.id} re-runs one reading twice over")
        if self.differences and (self.before_capture is None or self.after_capture is None):
            raise ValueError("a difference is recorded with no capture before and after it")
        for difference in self.differences:
            touching = next((c for c in self.applied_change if c.touches(difference.subject)), None)
            want = touching.label if touching else None
            if difference.explained_by != want:
                raise ValueError(
                    f"the difference on {difference.subject} says it is explained by "
                    f"{difference.explained_by!r}; the changes named say {want!r}"
                )

        judged = judge(
            self.reran,
            self.applied_change,
            self.before_capture,
            self.after_capture,
            self.differences,
        )
        for name in ("failing_now_passes", "no_regressions", "changes_explained"):
            if getattr(self, name) != getattr(judged, name):
                raise ValueError(
                    f"verification {self.id} says {name}={getattr(self, name)}; "
                    f"its readings say {getattr(judged, name)}"
                )
        if self.verdict is not judged.verdict:
            raise ValueError(
                f"verification {self.id} says {self.verdict.value}; its record supports "
                f"{judged.verdict.value}"
            )
        return self
