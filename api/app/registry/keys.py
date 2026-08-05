"""API key generation for the service registry.

Hashing reuses app.ingest_gateway.auth._hash_key rather than
reimplementing plain SHA-256 here — two independent copies of the same
hash function is exactly how a future change (e.g. switching algorithms)
ends up breaking only one side. ingest_gateway/auth.py's own comment on
why plain SHA-256 (not argon2/bcrypt) is the right choice for these
high-entropy generated tokens still applies unchanged.
"""

import secrets

from app.ingest_gateway.auth import _hash_key

#: "clp_live_" + 32 random bytes, url-safe-base64-encoded (43 chars) —
#: the "clp_live_" prefix makes a leaked key greppable/recognizable
#: (e.g. in a scanned commit or log line) the way GitHub/Stripe-style
#: prefixed tokens are.
_KEY_PREFIX = "clp_live_"


def generate_api_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(plaintext: str) -> str:
    return _hash_key(plaintext)
