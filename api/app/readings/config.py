from app.env import require_env

#: probe-writer role (Phase 31) — INSERT on `readings` and nothing else.
#: A new role rather than a widened one (.claude/rules/database.md), and
#: not the third reuse that file warns about: a credential that can post
#: readings is one that already has reach into a running environment,
#: which is a wider starting position than `fact-writer`'s repository-only
#: CI run or `capture-writer`'s declaration read. The argument in full is
#: in api/migrations/versions/a9d2c40f7e18_probe_readings.py.
#: No dev-password fallback -- see app/env.py and Phase 26.
PROBE_WRITER_DATABASE_URL = require_env(
    "PROBE_WRITER_DATABASE_URL", hint="see infra/.env.prod.example"
)
