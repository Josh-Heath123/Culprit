"""Required-environment reads that fail loudly.

Phase 26 (docs/DIAGNOSTIC_PLAN.md). Four `app/*/config.py` modules used
to fall back to a hardcoded `<role>-dev-password` when their
`*_DATABASE_URL` was unset. That is a fail-*open* default in the worst
place: a production deploy missing one variable did not crash, it
started up and quietly tried to connect as a least-privilege role using
a password that is committed to this repository. The failure surfaced,
if at all, as a confusing connection error much later — and on the day
someone provisioned a role with the dev password to "make it work", it
would not have surfaced at all.

The migrations under `api/migrations/versions/` have always done this
right (`_require_env`, raising rather than defaulting). This module is
that same behaviour for application config, in one place instead of
four, because unlike a migration — which must not import mutable
application code — nothing stops app modules from sharing it.

Deliberately *not* a Pydantic Settings class: these are read at import
time by modules that are imported transitively by almost everything,
and the value of failing here is that the traceback names the missing
variable in one line.
"""

import os


class MissingConfigError(RuntimeError):
    """Raised at import time when a required variable is unset."""


def require_env(name: str, *, hint: str = "") -> str:
    """Returns the value of `name`, or raises.

    An empty string counts as unset: an env var accidentally set to ""
    (a blank line in a `.env`, an unset shell variable interpolated into
    a compose file) is not a configured value, and treating it as one
    reintroduces exactly the fail-open behaviour this replaces.
    """
    value = os.environ.get(name)
    if value:
        return value
    message = f"{name} must be set in the environment"
    if hint:
        message = f"{message} ({hint})"
    raise MissingConfigError(message)
