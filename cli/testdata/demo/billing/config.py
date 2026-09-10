"""Configuration, read from the environment."""

import os

DATABASE_URL = os.environ["DATABASE_URL"]

#: Not in .env.example. That is the point: a fresh deploy comes up
#: without it and every webhook is rejected.
BILLING_WEBHOOK_SECRET = os.environ["BILLING_WEBHOOK_SECRET"]

REQUEST_TIMEOUT = os.environ.get("REQUEST_TIMEOUT", "30s")
