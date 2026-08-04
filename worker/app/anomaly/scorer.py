"""Pure EWMA/z-score anomaly scorer.

No Redis, no DB, no arq, no imports outside the standard library and
River. This must stay a pure, deterministic statistical computation —
per CLAUDE.md, anomaly detection is explicitly the one place in this
project where reaching for "just ask the LLM" is banned even for edge
cases like cold start or NaN guarding. See the import-linter contract in
pyproject.toml, which enforces this module never imports app.rag
(Phase 6) at the tooling level, not just by convention.
"""

import math

from river import stats

#: Cold-start guard: don't emit a score until this many observations have
#: been folded into the baseline. An EWMA/EWVar estimate built from a
#: handful of points is noise, not a baseline.
MIN_OBSERVATIONS = 30

#: Absolute floor for the standard deviation, so a flat/constant metric
#: (variance exactly 0) never causes a division blowup. Real metrics
#: (latency, error rate, request count) never have genuine variance
#: anywhere near this small.
MIN_STD = 1e-9

#: Relative floor, as a fraction of the running mean's magnitude. River's
#: EWVar computes variance as E[x^2] - E[x]^2 via two separately-tracked
#: EWMAs; even for a mathematically-constant series this doesn't cancel
#: to exactly 0 in float64 — empirically it leaves a residual on the
#: order of magnitude^2 * 1e-15. sqrt(float64 machine epsilon) is
#: ~1.5e-8; 1e-6 sits ~70x above that, comfortably clearing the observed
#: residual while staying far below any genuine variance a real metric
#: (latency, error rate, request count) would ever have.
RELATIVE_STD_FLOOR = 1e-6

#: The one global anomaly threshold. Per CLAUDE.md, this must NOT be
#: tuned per service or per metric — only the rolling *state* is kept
#: per (service_name, metric_name); the detection sensitivity itself
#: stays uniform. 3.0 is the standard "3-sigma" convention.
ANOMALY_THRESHOLD = 3.0

#: Same reasoning as ANOMALY_THRESHOLD: one global smoothing constant,
#: not tuned per service/metric. 0.1 gives an effective window of
#: roughly 2/alpha - 1 ~= 19 observations, a reasonable match for a
#: MIN_OBSERVATIONS=30 warm-up (long enough to smooth noise, short
#: enough to adapt to a genuine regime change within a demo run).
DEFAULT_FADING_FACTOR = 0.1


class MetricScorer:
    """EWMA-based rolling z-score for one (service_name, metric_name) series.

    Not thread-safe and holds no I/O — a plain in-memory object that
    Phase 4's Redis-persistence layer (app/anomaly/state.py) pickles
    between arq runs.
    """

    def __init__(self, fading_factor: float = DEFAULT_FADING_FACTOR) -> None:
        self.fading_factor = fading_factor
        self._mean = stats.EWMean(fading_factor=fading_factor)
        self._var = stats.EWVar(fading_factor=fading_factor)
        self.n = 0

    def update(self, x: float) -> float | None:
        """Score `x` against the baseline built from all *prior* points,
        then fold `x` into that baseline.

        Scoring happens before the update deliberately: if `x` were
        folded in first, an extreme outlier would immediately pull its
        own baseline toward it, damping the very deviation this is
        supposed to catch. Returns None during warm-up (see
        MIN_OBSERVATIONS).
        """
        score = None
        if self.n >= MIN_OBSERVATIONS:
            mean = self._mean.get()
            std = _safe_std(self._var.get(), mean)
            score = _safe_z(x, mean, std)
        # River's update() is typed as numbers.Number; float is a registered
        # virtual subclass at runtime but typeshed doesn't expose that
        # relationship, so pyright flags this as a mismatch. It isn't one.
        self._mean.update(x)  # pyright: ignore[reportArgumentType]
        self._var.update(x)  # pyright: ignore[reportArgumentType]
        self.n += 1
        return score


def _safe_std(variance: float, mean: float) -> float:
    floor = max(MIN_STD, abs(mean) * RELATIVE_STD_FLOOR) if math.isfinite(mean) else MIN_STD
    if not math.isfinite(variance) or variance <= floor * floor:
        return floor
    return math.sqrt(variance)


def _safe_z(x: float, mean: float, std: float) -> float:
    """Never returns NaN or infinity, for any finite x/mean/std. A
    computation that would otherwise overflow or divide into nonsense is
    treated as "no signal" (z=0.0) rather than a false anomaly or a crash.
    """
    if not (math.isfinite(x) and math.isfinite(mean) and math.isfinite(std)) or std <= 0:
        return 0.0
    z = (x - mean) / std
    return z if math.isfinite(z) else 0.0


def is_anomalous(z: float) -> bool:
    return abs(z) >= ANOMALY_THRESHOLD
