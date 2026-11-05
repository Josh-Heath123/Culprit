"""Pure EWMA/z-score anomaly scorer.

No Redis, no DB, no arq, no imports outside the standard library and
River. This must stay a pure, deterministic statistical computation —
per .claude/rules/determinism.md, anomaly detection is explicitly the one place in this
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

#: The one global anomaly threshold. Per .claude/rules/determinism.md, this must NOT be
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
    Phase 4's Redis-persistence layer (app/anomaly/state.py) serializes
    between arq runs via to_dict()/from_dict(), not pickle.

    Tracks variance as E[x^2] - E[x]^2 via two River EWMeans (`_mean` for
    x, `_sq_mean` for x^2) rather than river.stats.EWVar directly. Same
    formula EWVar itself uses internally (verified against it directly:
    identical output to the last float digit) — the difference is that
    EWMean's own state is round-trippable through its public API (a
    freshly constructed EWMean's *first* update() call sets its .get()
    to exactly that value, no blending with an initial 0), so to_dict()/
    from_dict() can persist and exactly restore this scorer as plain
    JSON floats. EWVar has no equivalent public seam — restoring it
    to an arbitrary target variance isn't achievable through its API,
    which is what made pickling the only option before this change.
    """

    def __init__(self, fading_factor: float = DEFAULT_FADING_FACTOR) -> None:
        self.fading_factor = fading_factor
        self._mean = stats.EWMean(fading_factor=fading_factor)
        self._sq_mean = stats.EWMean(fading_factor=fading_factor)
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
            variance = max(self._sq_mean.get() - mean * mean, 0.0)
            std = _safe_std(variance, mean)
            score = _safe_z(x, mean, std)
        # River's update() is typed as numbers.Number; float is a registered
        # virtual subclass at runtime but typeshed doesn't expose that
        # relationship, so pyright flags this as a mismatch. It isn't one.
        self._mean.update(x)  # pyright: ignore[reportArgumentType]
        self._sq_mean.update(x * x)  # pyright: ignore[reportArgumentType]
        self.n += 1
        return score

    def to_dict(self) -> dict:
        """JSON-safe snapshot — plain floats/int only, no pickle. `mean`/
        `sq_mean` are None before the first update() (nothing to persist
        yet); from_dict() leaves a fresh scorer's EWMeans un-seeded in
        that case, which is exactly what __init__ already does."""
        return {
            "fading_factor": self.fading_factor,
            "n": self.n,
            "mean": self._mean.get() if self.n > 0 else None,
            "sq_mean": self._sq_mean.get() if self.n > 0 else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MetricScorer":
        scorer = cls(fading_factor=data["fading_factor"])
        scorer.n = data["n"]
        if data["mean"] is not None:
            # A freshly constructed EWMean's first update() sets .get()
            # to exactly that value (no blending with an unset initial
            # state) — this is a seed, not a real observation, and
            # doesn't count toward `n` (already restored above).
            scorer._mean.update(data["mean"])  # pyright: ignore[reportArgumentType]
            scorer._sq_mean.update(data["sq_mean"])  # pyright: ignore[reportArgumentType]
        return scorer


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
