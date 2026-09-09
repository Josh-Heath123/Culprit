"""The system model (Phase 27) — components, typed connections and the
contracts between them.

Split from `api/app/registry/`, which now keeps only the parts that are
not the model itself: ingest API keys and the Phase 19 topology
suggestion queue. See `api/app/model/router.py` for the HTTP surface and
`api/app/registry/router.py` for the `/services*` aliases retained for
one release (Phase 27 field 9).
"""
