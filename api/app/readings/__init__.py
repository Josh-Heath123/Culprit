"""`/readings` and `/probes` — Phase 31, the OBSERVED plane's HTTP surface.

Three routes, and the split between them is the honest part.

`POST /readings` stores what a probe measured. `GET /probes` describes
what probes exist. `POST /probes/{id}/run` cannot run one, and says so:
probes execute inside the `culprit` binary (docs/DIAGNOSTIC_PLAN.md
Phase 31 field 3), and this API has no transport to reach an agent until
Phase 33. It answers 503 and names the local command instead of
fabricating a reading, because a made-up measurement is worse than no
measurement — it is indistinguishable from a real one once stored.
"""
