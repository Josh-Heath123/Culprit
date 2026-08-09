"""No new DB URL constant here, unlike every other domain package's own
config.py (app/postmortems/config.py, app/registry/config.py). Phase 21
(docs/AI_NATIVE_PLAN.md) deliberately extends `postmortem-writer`'s
existing grants to cover `architecture_decisions`/`ai_change_records`
rather than minting a new role (invariant 10 — same trust domain as
`postmortems`) — so this package's writes reuse the exact same engine
`app/main.py` already builds from `app.postmortems.config.
POSTMORTEM_WRITER_DATABASE_URL` and stores at
`app.state.postmortem_session_factory`. Reads reuse `app.state.
session_factory` (api-reader), same as every other domain's GET
endpoints. This file exists so the package's shape still matches
`app/postmortems/`'s five-file convention, not because it has anything to
configure.
"""
