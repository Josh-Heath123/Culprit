"""The agent request-signing contract, the Python half (Phase 33 part 2).

The Go half is `cli/internal/agentauth`; both are held to
`shared/tests/agent_signing_conformance.json`. An agent signs, with its
Ed25519 key, a canonical form of every request it sends:

    culprit-agent-v1
    METHOD
    /path/relative/to/the/api/root
    hex sha256 of the body
    unix timestamp
    nonce (32 lowercase hex digits)
    agent id

The control plane rebuilds that form from what it actually received — the
method and path of the request it is handling, the digest of the body bytes
it read — so a signature vouches for one request and nothing else. It
refuses a request whose key is unknown or revoked, whose timestamp is more
than MAX_SKEW_SECONDS from its clock, whose nonce it has seen, or whose
signature does not verify; and it does not say which.

Pure: no database, no clock of its own. The nonce store and the key lookup
are the dependency's (app/agents/dependencies.py).
"""

import base64
import binascii
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEME = "culprit-agent-v1"
MAX_SKEW_SECONDS = 300

HEADER_AGENT = "X-Culprit-Agent"
HEADER_TIMESTAMP = "X-Culprit-Timestamp"
HEADER_NONCE = "X-Culprit-Nonce"
HEADER_SIGNATURE = "X-Culprit-Signature"

_NONCE = re.compile(r"^[0-9a-f]{32}$")
AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class SignedRequest:
    method: str
    path: str
    body: bytes
    timestamp: int
    nonce: str
    agent_id: str


@dataclass(frozen=True)
class AgentKey:
    public_key: bytes
    revoked: bool


def canonical(request: SignedRequest) -> bytes:
    return "\n".join(
        [
            SCHEME,
            request.method.upper(),
            request.path,
            hashlib.sha256(request.body).hexdigest(),
            str(request.timestamp),
            request.nonce,
            request.agent_id,
        ]
    ).encode("utf-8")


def well_formed(request: SignedRequest) -> bool:
    return (
        bool(_NONCE.match(request.nonce))
        and bool(AGENT_ID.match(request.agent_id))
        and request.path.startswith("/")
        and request.timestamp > 0
    )


def fresh(timestamp: int, now: int) -> bool:
    return abs(now - timestamp) <= MAX_SKEW_SECONDS


def signature_valid(public_key: bytes, request: SignedRequest, signature: str) -> bool:
    try:
        raw = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(raw) != 64 or len(public_key) != 32:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(raw, canonical(request))
    except InvalidSignature:
        return False
    return True


def decide(
    key: AgentKey | None,
    request: SignedRequest,
    signature: str,
    now: int,
    seen: Callable[[str], bool],
) -> bool:
    """The whole decision, in the order the fixture states it. The nonce
    is checked last, so a request that fails anything else never consumes
    one."""
    if key is None or key.revoked:
        return False
    if not well_formed(request) or not fresh(request.timestamp, now):
        return False
    if not signature_valid(key.public_key, request, signature):
        return False
    return not seen(request.nonce)
