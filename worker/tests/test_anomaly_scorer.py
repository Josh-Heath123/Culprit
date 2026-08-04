"""Property tests for the pure scorer (app/anomaly/scorer.py).

Written and passing before any Redis/DB/arq wiring exists, per the plan's
own reasoning: don't debug statistics and plumbing at the same time.
"""

import math

from app.anomaly.scorer import MIN_OBSERVATIONS, MetricScorer
from hypothesis import given
from hypothesis import strategies as st

finite_floats = st.floats(allow_nan=False, allow_infinity=False)


@given(st.lists(finite_floats, min_size=1, max_size=200))
def test_score_is_never_nan_or_infinite(values: list[float]) -> None:
    scorer = MetricScorer()
    for x in values:
        score = scorer.update(x)
        if score is not None:
            assert math.isfinite(score)


@given(finite_floats, st.integers(min_value=MIN_OBSERVATIONS + 1, max_value=MIN_OBSERVATIONS + 50))
def test_constant_sequence_scores_near_zero(value: float, count: int) -> None:
    """"Near zero" rather than exactly zero: at extreme magnitudes (>1e15
    or so — far beyond any real latency/error-rate/count metric), float64
    itself can't represent River's running mean with enough precision to
    keep x - mean exactly 0, so the scorer's relative-magnitude floor (see
    RELATIVE_STD_FLOOR) is what keeps the result well below the anomaly
    threshold rather than an exact zero.
    """
    scorer = MetricScorer()
    scores = [scorer.update(value) for _ in range(count)]
    scored = [s for s in scores if s is not None]
    assert scored, "expected at least one score once past the warm-up window"
    for z in scored:
        assert abs(z) < 1.0


#: fading_factor=0 (or values indistinguishable from it) freezes the
#: state at its initial value forever — not a "wide window", a broken
#: configuration nothing in this system ever uses (DEFAULT_FADING_FACTOR
#: is 0.1). Restricting to [0.01, 0.99] keeps this property about the
#: realistic operating range rather than a degenerate edge case that
#: produces essentially undefined behavior in the underlying library.
realistic_fading_factors = st.floats(min_value=0.01, max_value=0.99)


@given(
    baseline=finite_floats,
    deviation=finite_floats.filter(lambda d: d != 0),
    fading_a=realistic_fading_factors,
    fading_b=realistic_fading_factors,
)
def test_wider_window_is_never_more_sensitive(
    baseline: float, deviation: float, fading_a: float, fading_b: float
) -> None:
    """A wider rolling window (smaller fading_factor) must never produce a
    stricter (larger-magnitude) threshold crossing than a narrower one, for
    the same input.

    Constructed so this is provably true rather than merely typical: a
    long constant run makes River's EWMean/EWVar converge to the same
    (mean, variance) state regardless of fading_factor (verified
    empirically — see Phase 4 notes), so both scorers see an equivalent
    baseline going into the final, deviating point. At extreme baseline
    magnitudes (>1e15), float64 can't represent that convergence exactly,
    leaving residual noise on the order of 1e-6 in both branches — a
    generous absolute tolerance keeps the assertion about the real
    property (does widening the window ever make detection *meaningfully*
    more sensitive) rather than about ordering two numbers that are both
    already indistinguishable from zero relative to ANOMALY_THRESHOLD.
    """
    fading_wide, fading_narrow = sorted((fading_a, fading_b))

    def score_after_spike(fading_factor: float) -> float:
        scorer = MetricScorer(fading_factor=fading_factor)
        for _ in range(MIN_OBSERVATIONS):
            scorer.update(baseline)
        z = scorer.update(baseline + deviation)
        assert z is not None
        return z

    z_wide = score_after_spike(fading_wide)
    z_narrow = score_after_spike(fading_narrow)

    # A pure absolute tolerance breaks down at large magnitudes (float64's
    # own ULP grows with magnitude), and a pure relative tolerance breaks
    # down near zero — math.isclose's combination of both handles both
    # regimes without masking a real, orders-of-magnitude violation.
    assert abs(z_wide) <= abs(z_narrow) or math.isclose(
        abs(z_wide), abs(z_narrow), rel_tol=1e-6, abs_tol=1e-3
    )
