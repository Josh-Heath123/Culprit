"""Required-environment reads that fail loudly.

Phase 26 (docs/DIAGNOSTIC_PLAN.md). The worker's four `*_DATABASE_URL`
reads in `app/main.py` used to fall back to a hardcoded
`<role>-dev-password`, the same fail-open defect the four
`api/app/*/config.py` modules had: a deploy missing one variable started
up and tried to connect as a least-privilege role using a password
committed to this repository, instead of refusing to start.

A deliberate ten-line duplicate of `api/app/env.py`, not an import of
it. `api` and `worker` are separate uv projects with no shared
internals (CLAUDE.md); `shared/` exists for *contracts* the two must
agree on over the wire, and a local helper for reading environment
variables is not one. Copying ten lines is the smaller cost.
"""

import os


class MissingConfigError(RuntimeError):
    """Raised at import time when a required variable is unset."""


def require_env(name: str, *, hint: str = "") -> str:
    """Returns the value of `name`, or raises.

    An empty string counts as unset: an env var accidentally set to ""
    is not a configured value, and treating it as one reintroduces the
    fail-open behaviour this replaces.
    """
    value = os.environ.get(name)
    if value:
        return value
    message = f"{name} must be set in the environment"
    if hint:
        message = f"{message} ({hint})"
    raise MissingConfigError(message)
