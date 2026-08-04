"""slowapi Limiter, in its own module so both app/main.py (registers the
exception handler + middleware) and app/incidents/router.py (decorates
the one endpoint that needs it) import the same instance.

Only POST /incidents/{id}/regenerate-root-cause is rate-limited — that's
the one endpoint that triggers a new Claude + Voyage call downstream (via
the arq job it enqueues), per docs/IMPLEMENTATION_PLAN.md's security
checklist: rate limiting specifically on endpoints that trigger an LLM
call, cost/abuse control rather than general throttling. The two GET
endpoints are plain reads against the api-reader role and aren't
rate-limited here.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
