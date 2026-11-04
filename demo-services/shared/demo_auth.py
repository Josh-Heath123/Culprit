"""Service-to-service bearer tokens for the demo — the audience check that
Phase 32's fault library breaks on purpose.

order-service presents a token to inventory-service; inventory-service
checks its audience. The fault is a token minted for the wrong audience —
a config fault on order-service that surfaces as a 401 on inventory-service
and a 502 at the edge, which is exactly the case the isolation walk has to
trace back past the 500 the user saw.

Standard library only (HS256 with hmac), because the demo is not the place
to add a dependency (DIAGNOSTIC_PLAN.md Phase 32 field 11). This is a demo
check, not an auth library: it verifies the signature, expiry and audience,
and nothing else.
"""

import base64
import hashlib
import hmac
import json
import time


def _b64decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify(authorization: str | None, secret: str, audience: str) -> str | None:
    """Return why a bearer token is not acceptable, or None if it is.

    The reasons are fixed phrases: a demo service logging the token it
    refused would be teaching the wrong lesson.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return "no bearer token"
    token = authorization.removeprefix("Bearer ").strip()
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError:
        return "not a JWT"
    expected = hmac.new(
        secret.encode(), f"{header_segment}.{payload_segment}".encode(), hashlib.sha256
    ).digest()
    try:
        signature = _b64decode(signature_segment)
        claims = json.loads(_b64decode(payload_segment))
    except (ValueError, json.JSONDecodeError):
        return "not a JWT"
    if not hmac.compare_digest(expected, signature):
        return "bad signature"
    if "exp" in claims and time.time() >= float(claims["exp"]):
        return "expired"
    audiences = claims.get("aud")
    if isinstance(audiences, str):
        audiences = [audiences]
    if audience not in (audiences or []):
        return "wrong audience"
    return None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(secret: str, audience: str, issuer: str = "order-service", ttl_s: int = 86400) -> str:
    """An HS256 token `verify` accepts for `audience` — or, minted for any
    other audience, the fault (`just quickstart` mints both). The same
    construction as the fault library's `mintToken` in
    cli/cmd/culprit/faultlib_test.go."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"aud": audience, "iss": issuer, "exp": int(time.time()) + ttl_s}
    payload = _b64encode(json.dumps(claims).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64encode(signature)}"


if __name__ == "__main__":
    # python -m shared.demo_auth <audience>, with DEMO_TOKEN_SECRET in the
    # environment rather than on the command line.
    import os
    import sys

    print(mint(os.environ["DEMO_TOKEN_SECRET"], sys.argv[1]))
