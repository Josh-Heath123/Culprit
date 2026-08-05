import os

INGEST_GATEWAY_DATABASE_URL = os.environ["INGEST_GATEWAY_DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# Phase 15: the public ingest path. Generous relative to a 10-second OTel
# export interval across a handful of services, tight enough to matter —
# see docs/SELF_HOSTED_PLAN.md's Phase 15 hardening steps.
INGEST_RATE_LIMIT = os.environ.get("INGEST_RATE_LIMIT", "600/minute")

_SIZE_SUFFIXES = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}


def _parse_size_bytes(value: str) -> int:
    """Parses a Caddy-style size string ("5MB", "512KB", or a bare byte
    count) — the same INGEST_MAX_BODY_BYTES value drives both
    frontend/Caddyfile's `max_size {$INGEST_MAX_BODY_BYTES:5MB}` and this
    module, so it has to be one format both sides agree on rather than
    asking whoever sets it in infra/.env.prod.example to pick a format
    per consumer."""
    value = value.strip().upper()
    for suffix, multiplier in _SIZE_SUFFIXES.items():
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * multiplier)
    return int(value)


#: Applies to the *decompressed* body (see main.py's _maybe_decompress) —
#: Caddy's own request_body max_size (frontend/Caddyfile) caps the raw,
#: still-possibly-gzipped body arriving from outside; this is the
#: gateway's own defensive check, both for traffic that reaches it
#: directly on the compose network (bypassing Caddy) and for the actual
#: gzip-bomb case Caddy's cap can't see at all.
INGEST_MAX_BODY_BYTES = _parse_size_bytes(os.environ.get("INGEST_MAX_BODY_BYTES", "5MB"))
