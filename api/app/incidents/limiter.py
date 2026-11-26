# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""slowapi Limiter, in its own module so both app/main.py (registers the
exception handler + middleware) and the routers that rate-limit (sign-in,
POST /auth/login, at 10 a minute) import the same instance.

# Keyed on the caller's address, as Caddy saw it (F44-015)

Behind Caddy every request reaches the api from Caddy's own address, so a
limit keyed on the peer was one bucket for everyone: ten failed sign-ins a
minute from anyone locked the whole team out. The caller's address is in
X-Forwarded-For, which Caddy sets — and which anyone can send. So the
header is believed only from the one hop the compose files declare, by
service name (`TRUSTED_PROXY_HOST: frontend`), resolved to its addresses
and re-resolved every half minute; from any other peer it is ignored and
the peer is the key. Unset, or unresolvable, nothing is trusted: the
limit falls back to the peer, as it was. Caddy replaces an X-Forwarded-For
it receives from an untrusted client with that client's address, so the
last entry is the caller; the last is taken either way.
"""

import os
import socket
import time

from slowapi import Limiter
from starlette.requests import Request

#: The compose service name of the one proxy in front of the api.
TRUSTED_PROXY_HOST = os.environ.get("TRUSTED_PROXY_HOST", "").strip()

#: How long a resolution of TRUSTED_PROXY_HOST is kept.
_RESOLVE_EVERY_S = 30.0
_resolved: tuple[float, frozenset[str]] = (0.0, frozenset())


def _resolve(host: str) -> frozenset[str]:
    try:
        return frozenset(str(info[4][0]) for info in socket.getaddrinfo(host, None))
    except OSError:
        return frozenset()


def proxy_addresses() -> frozenset[str]:
    """The addresses TRUSTED_PROXY_HOST resolves to now, or none."""
    global _resolved
    if not TRUSTED_PROXY_HOST:
        return frozenset()
    at, addresses = _resolved
    if time.monotonic() - at > _RESOLVE_EVERY_S:
        addresses = _resolve(TRUSTED_PROXY_HOST)
        _resolved = (time.monotonic(), addresses)
    return addresses


def client_address(request: Request) -> str:
    """The address a rate limit is kept for: the caller's, as the trusted
    proxy saw it, or the peer's when the peer is not that proxy."""
    peer = request.client.host if request.client else ""
    if TRUSTED_PROXY_HOST and peer and peer in proxy_addresses():
        hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [hop for hop in hops if hop]
        if hops:
            return hops[-1]
    return peer or "unknown"


limiter = Limiter(key_func=client_address)
