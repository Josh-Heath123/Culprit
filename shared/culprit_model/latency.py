"""Latency budgets, and the rule that judges a latency reading — Phase 36.

A declared budget is the reference a measured latency diverges from
(`docs/PERFORMANCE_PLAN.md` §0.1, P1, P2). This module holds both halves:

- `Budget`: one entry of `culprit.yaml`'s `budgets:`, refused unless its
  predicate is in the closed set `BUDGET_PREDICATES`.
- `judge(measured, expected)`: the verdict a latency reading must carry,
  as a pure function of its own samples and its budget. `Reading`
  refuses a `probe.http.latency` reading whose verdict this does not give,
  so the API refuses one wherever it arrives.

The Go half is `cli/internal/model/latency.go`. Both are held to
`shared/tests/latency_conformance.json`, verdicts and reasons alike.

**Integer arithmetic only.** Samples are whole microseconds. A percentile
is the nearest-rank order statistic. Its bounds are the order statistics
at the ranks the exact binomial gives for `CONFIDENCE` percent on each
side, computed with integers (`100^n` and binomial coefficients), so Go and
Python cannot disagree in a last digit.

- **fail** when the lower bound is over the budget;
- **pass** when the upper bound is within it;
- **inconclusive** otherwise: the interval straddles the budget, or there
  are too few samples for a bound to exist. No width threshold: any would
  be a number Culprit chose (§4).

A timeout is a sample slower than any answer: dropping it would report a
service that has stopped answering as fast. An answer other than `2xx` is
not a sample at all — it measures a refusal, not the route.

Deterministic and dependency-free (`.claude/rules/determinism.md`).
"""

import re
from math import comb
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from culprit_model.subjects import SubjectError, SubjectKind
from culprit_model.subjects import build as build_subject
from culprit_model.subjects import parse as parse_subject

#: The probe whose readings this rule judges.
LATENCY_PROBE_ID = "probe.http.latency"
#: The confidence of each one-sided bound, in percent. One constant; LIMITS
#: states it.
CONFIDENCE = 90
#: The predicates a budget may name, and the percentile each declares.
#: Grown one phase at a time (P1): p50 and p95 in Phase 36.
BUDGET_PREDICATES: dict[str, int] = {"latency_p50_ms": 50, "latency_p95_ms": 95}
#: The most requests one latency reading may record — the probe's hard cap.
MAX_REQUESTS = 50
#: The largest budget, in milliseconds. Not a threshold Culprit judges by:
#: a bound on what can be declared, because the probe's whole run is 120 s
#: and a request must be able to take longer than the budget for a timeout
#: to mean "slower than the budget". Go holds the same number.
MAX_BUDGET_MS = 60_000
#: The largest sample, in microseconds: no request is timed past the
#: probe's 120 s run, so anything above this is not a measurement.
MAX_SAMPLE_US = 1_000_000_000

INCONCLUSIVE = "inconclusive"
PASS = "pass"
FAIL = "fail"


class LatencyShapeError(ValueError):
    """A latency reading whose measured or expected values are not the
    rule's inputs."""


#: A budget as written in culprit.yaml: plain decimal digits, no sign, no
#: leading zero, unquoted.
_PLAIN_DECIMAL = re.compile(r"[1-9][0-9]*")


#: The refusal of a budget entry with a merge key (`<<`): the fields it
#: brings in are not checked for their form. Go holds the same sentence as
#: model.BudgetMergeProblem.
BUDGET_MERGE_PROBLEM = "a budget entry is written out in full: a merge key (<<) is not read"


def budget_literal_problem(literal: str, plain: bool) -> str | None:
    """Why a budget's value, as written in YAML, is not a plain decimal
    integer — or None when it is. `plain` is whether the scalar was written
    unquoted, with no tag or alias.

    Phase 36 part 2: the two YAML readers of one INTENT value read some
    forms differently. YAML 1.1 (PyYAML) reads `0454` as octal 300 and
    `300_000` as 300000, and `1e3` and `0o454` as strings; YAML 1.2 (Go's
    yaml.v3) reads `1e3` as 1000 and `0o454` as 300. Two readers must not
    read two values, so both refuse every form but this one, each from
    `shared/tests/latency_conformance.json`'s `budget_literals`. The Go
    half is model.BudgetLiteralProblem."""
    if not plain:
        return "a budget is written as plain decimal digits, without quotes, a tag or an alias"
    if _PLAIN_DECIMAL.fullmatch(literal) is None:
        # Never the literal itself: error text is output, and a value
        # pasted in the wrong place can be a credential (invariant 7).
        return "a budget is written as plain decimal digits, and this value is not"
    return None


class Budget(BaseModel):
    """One `budgets:` entry: a rank-100 INTENT fact about how fast a
    subject must be. The Go loader is `cli/internal/extract/budgets.go`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(min_length=1)
    predicate: str
    #: Whole milliseconds, 1 to MAX_BUDGET_MS. A float with no fraction is
    #: accepted here, as JSON decoded in Go gives one; in culprit.yaml both
    #: YAML readers refuse every form but plain decimal digits first
    #: (`budget_literal_problem`).
    value: int
    #: Required, as for an invariant: a budget nobody explained is one
    #: nobody can safely change.
    why: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def _value_is_whole_milliseconds(cls, value: Any) -> int:
        try:
            return _int(value, "a budget", minimum=1, maximum=MAX_BUDGET_MS)
        except LatencyShapeError as exc:
            raise ValueError(f"{exc} (milliseconds)") from None

    @field_validator("predicate")
    @classmethod
    def _predicate_is_known(cls, value: str) -> str:
        if value not in BUDGET_PREDICATES:
            raise ValueError(
                f"budget predicate {value!r} is not one of {sorted(BUDGET_PREDICATES)}"
            )
        return value

    @field_validator("subject")
    @classmethod
    def _subject_is_canonical(cls, value: str) -> str:
        try:
            kind, parts = parse_subject(value)
            rebuilt = build_subject(SubjectKind(kind), **parts)
        except (SubjectError, ValueError) as exc:
            raise ValueError(f"budget subject {value!r} is not a subject URI") from exc
        if rebuilt != value:
            raise ValueError(f"budget subject {value!r} is not in canonical form ({rebuilt!r})")
        return value


# ---- the rule ------------------------------------------------------------------


def _int(value: Any, name: str, minimum: int = 0, maximum: int | None = None) -> int:
    # bool is an int in Python; a JSON true is not a count. A float with no
    # fraction is accepted, because JSON decoded in Go arrives as one.
    if isinstance(value, bool):
        raise LatencyShapeError(f"{name} must be a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise LatencyShapeError(f"{name} must be a whole number")
        value = int(value)
    if not isinstance(value, int) or value < minimum:
        raise LatencyShapeError(f"{name} must be a whole number of at least {minimum}")
    if maximum is not None and value > maximum:
        raise LatencyShapeError(f"{name} must be at most {maximum}")
    return value


def lower_rank(n: int, percentile: int) -> int | None:
    """The largest rank l with P(Binomial(n, p) >= l) >= CONFIDENCE%: the
    l-th smallest sample is at or below the true percentile with that
    confidence. None when even rank 1 falls short."""
    total = 100**n
    tail = 0
    for rank in range(n, 0, -1):
        tail += comb(n, rank) * percentile**rank * (100 - percentile) ** (n - rank)
        if 100 * tail >= CONFIDENCE * total:
            return rank
    return None


def upper_rank(n: int, percentile: int) -> int | None:
    """The smallest rank u with P(Binomial(n, p) <= u - 1) >= CONFIDENCE%:
    the u-th smallest sample is at or above the true percentile with that
    confidence. None when even rank n falls short."""
    total = 100**n
    head = 0
    for rank in range(1, n + 1):
        below = rank - 1
        head += comb(n, below) * percentile**below * (100 - percentile) ** (n - below)
        if 100 * head >= CONFIDENCE * total:
            return rank
    return None


def _ms(microseconds: int | None) -> str:
    if microseconds is None:
        return "a timeout"
    return f"{microseconds // 1000}.{microseconds % 1000:03d} ms"


def planned_requests(measured: dict[str, Any]) -> int | None:
    """How many requests the run set out to send (`planned`), or None when
    the reading does not say. Phase 36 part 2: a run cut short by its
    deadline is judged inconclusive, whatever the samples it has say, so
    the count stays fixed and nothing stops early."""
    if "planned" not in measured:
        return None
    planned = _int(measured.get("planned"), "planned", minimum=1, maximum=MAX_REQUESTS)
    return planned


def inputs(
    measured: dict[str, Any], expected: dict[str, Any] | None
) -> tuple[int, int, int, list[int], int]:
    """The rule's inputs, validated: (percentile, budget in ms, requests,
    answered samples in microseconds, timeouts)."""
    percentile = _int(measured.get("percentile"), "percentile")
    if percentile not in BUDGET_PREDICATES.values():
        raise LatencyShapeError(f"percentile {percentile} is not one a budget can declare")
    requests = _int(measured.get("requests"), "requests")
    if requests > MAX_REQUESTS:
        raise LatencyShapeError(f"requests {requests} is over the cap of {MAX_REQUESTS}")
    planned = planned_requests(measured)
    if planned is not None and requests > planned:
        raise LatencyShapeError(f"requests {requests} is more than the {planned} planned")
    raw = measured.get("samples_us")
    if not isinstance(raw, list):
        raise LatencyShapeError("samples_us must be a list")
    samples = [_int(item, "a sample", maximum=MAX_SAMPLE_US) for item in raw]
    timeouts = _int(measured.get("timeouts"), "timeouts")
    if len(samples) + timeouts > requests:
        raise LatencyShapeError("more samples and timeouts than requests")
    if not isinstance(expected, dict):
        raise LatencyShapeError("a latency reading must carry its budget in expected")
    declared = [key for key in expected if key in BUDGET_PREDICATES]
    if len(declared) != 1:
        raise LatencyShapeError("expected must name exactly one budget predicate")
    if BUDGET_PREDICATES[declared[0]] != percentile:
        raise LatencyShapeError(f"the budget is {declared[0]} but p{percentile} was measured")
    budget = _int(expected[declared[0]], "the budget", minimum=1, maximum=MAX_BUDGET_MS)
    return percentile, budget, requests, samples, timeouts


def judge(measured: dict[str, Any], expected: dict[str, Any] | None) -> tuple[str, str]:
    """(verdict, reason) for a latency measurement against its budget.
    Raises LatencyShapeError when the inputs are not the rule's."""
    percentile, budget, requests, samples, timeouts = inputs(measured, expected)
    # Timeouts sort after every answer: slower than any of them.
    ordered: list[int | None] = [*sorted(samples), *([None] * timeouts)]
    n = len(ordered)
    limit = budget * 1000
    planned = planned_requests(measured)
    if planned is not None and requests < planned:
        return INCONCLUSIVE, (
            f"the run was cut short at its deadline: {requests} of {planned} requests were "
            f"sent, so p{percentile} is not judged against the {budget} ms budget"
        )
    if n == 0:
        return INCONCLUSIVE, (
            f"no sample: none of {requests} requests answered 2xx or timed out, "
            f"so p{percentile} was not measured"
        )

    def over(value: int | None) -> bool:
        return value is None or value > limit

    lower = lower_rank(n, percentile)
    upper = upper_rank(n, percentile)
    if lower is not None and over(ordered[lower - 1]):
        return FAIL, (
            f"p{percentile} is over the {budget} ms budget: at {CONFIDENCE}% confidence "
            f"it is at least {_ms(ordered[lower - 1])} (sample {lower} of {n})"
        )
    if upper is not None and not over(ordered[upper - 1]):
        return PASS, (
            f"p{percentile} is within the {budget} ms budget: at {CONFIDENCE}% confidence "
            f"it is at most {_ms(ordered[upper - 1])} (sample {upper} of {n})"
        )
    low = (
        f"at least {_ms(ordered[lower - 1])} (sample {lower})"
        if lower is not None
        else "no lower bound"
    )
    high = (
        f"at most {_ms(ordered[upper - 1])} (sample {upper})"
        if upper is not None
        else "no upper bound"
    )
    reason = (
        f"p{percentile} cannot be placed against the {budget} ms budget at {CONFIDENCE}% "
        f"confidence from {n} samples: {low}, {high}"
    )
    if requests > n:
        reason += f"; {requests - n} of {requests} requests did not answer 2xx and are not samples"
    return INCONCLUSIVE, reason
