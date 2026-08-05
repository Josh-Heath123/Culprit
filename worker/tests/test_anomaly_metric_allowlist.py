"""Phase 14: worker/app/anomaly/job.py stops scoring every metric a
service happens to send and instead honours that service's
monitored_metrics allowlist (services.monitored_metrics). An empty list
must mean "score everything" -- the pre-Phase-14 behaviour -- not "score
nothing", so that existing/unregistered services keep working unchanged.
"""

from app.anomaly.job import _metric_allowed


def test_empty_allowlist_scores_everything() -> None:
    assert _metric_allowed("http.server.duration", [])
    assert _metric_allowed("anything.at.all", [])


def test_populated_allowlist_scores_only_its_members() -> None:
    allowlist = ["http.server.duration", "http.server.errors"]
    assert _metric_allowed("http.server.duration", allowlist)
    assert _metric_allowed("http.server.errors", allowlist)
    assert not _metric_allowed("some.other.metric", allowlist)
