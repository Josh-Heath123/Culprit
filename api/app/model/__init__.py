"""The system model (Phase 27) — components, typed connections and the
contracts between them.

Split from `api/app/registry/`, which now keeps only the parts that are
not the model itself: ingest API keys and the Phase 19 topology
suggestion queue. `api/app/model/router.py` is the HTTP surface for all
of it — the `/services*` aliases Phase 27 retained for one release were
removed in Phase 30 (field 6).
"""
