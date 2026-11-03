"""Import-time environment for the worker's tests.

Phase 26 (docs/DIAGNOSTIC_PLAN.md) removed `app/main.py`'s fail-open
`<role>-dev-password` fallbacks for its four `*_DATABASE_URL` reads, so
importing `app.main` now correctly refuses to proceed without them.
`test_placeholder.py` imports it to check the arq job registration, so
the values have to come from somewhere — a test harness is the right
somewhere, and mirrors what `api/tests/conftest.py` already does.

Nothing here is connected to. Every worker test that needs a real
database builds its own URL against a throwaway container; these exist
only to satisfy reads that happen at module import.

`setdefault`, not assignment, so a real `worker/.env` or a CI-provided
value always wins.
"""

import os

_IMPORT_TIME_DEFAULTS = {
    "DATABASE_URL": "postgresql+asyncpg://ingestion-writer:test@localhost:5432/test",
    "ANOMALY_DATABASE_URL": "postgresql+asyncpg://anomaly-detector:test@localhost:5432/test",
    "CORRELATION_DATABASE_URL": "postgresql+asyncpg://correlation-engine:test@localhost:5432/test",
    "ROOT_CAUSE_DATABASE_URL": "postgresql+asyncpg://root-cause-writer:test@localhost:5432/test",
    "PROBE_WRITER_DATABASE_URL": "postgresql+asyncpg://probe-writer:test@localhost:5432/test",
}

for _name, _value in _IMPORT_TIME_DEFAULTS.items():
    os.environ.setdefault(_name, _value)
