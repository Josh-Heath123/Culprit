"""slowapi Limiter for ingest-gateway (Phase 15), in its own module for
the same reason app/incidents/limiter.py is: app/ingest_gateway/main.py
(exception handler + middleware) and the route decorators need the same
instance.

Keyed by the authenticated `service_name`, not client IP — every service
behind one NAT (a third party's own infra, likely one VM/cluster egress
IP for several services) would otherwise share one bucket, so one noisy
service throttles all the others. Falls back to the client IP only for
requests that never get an authenticated identity at all (missing/
malformed/invalid key) — slowapi still needs *some* key to count against
even for those, and a shared "no identity" bucket keyed by IP is the
closest available approximation of the real caller.

Per Known Trap 4, this is deliberately NOT built on "read the service
name the route's own auth dependency already resolved" — slowapi's
`@limiter.limit(...)` decorator runs its key function as part of its own
request handling, and whether that happens before or after FastAPI has
resolved `Depends(authenticated_service_name)` on the same route is a
framework-internals detail not worth depending on (see
tests/test_ingest_gateway_limits.py, which asserts the actual observed
behavior rather than this docstring's belief about it). Re-deriving
identity directly — hashing the presented key the same way
ingest_gateway/auth.py does and looking it up in the same in-memory
store — sidesteps the ordering question entirely rather than resolving
it: it works whichever order slowapi and FastAPI actually run in.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.ingest_gateway.auth import _hash_key, api_key_store


def _rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        presented_key = authorization.removeprefix("Bearer ").strip()
        entry = api_key_store._match(_hash_key(presented_key))
        if entry is not None:
            service_name, _key_id = entry
            return f"service:{service_name}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_rate_limit_key)
