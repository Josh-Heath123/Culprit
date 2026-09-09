"""Config reads, in the three spellings the static scanner recognises."""

import os

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
PORT = os.environ.get("PORT", "8000")
REQUEST_TIMEOUT = os.getenv("REQUEST_TIMEOUT", "30s")
FEATURE_ASYNC_FULFILMENT = os.environ.get("FEATURE_ASYNC_FULFILMENT", "false")

# A read with a computed key: deliberately not extractable, and skipped
# rather than guessed at. A subject built from a guess would never match
# anything and would sit in the report as a permanent phantom.
_PREFIX = "STRIPE_"
STRIPE_API_KEY = os.environ.get(_PREFIX + "API_KEY", "")
