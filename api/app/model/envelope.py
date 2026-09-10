"""Opening a sealed capture envelope — the Python half of
`cli/internal/capture/envelope.go`.

Phase 30 field 7: "A capture is a signed, timestamped bundle." The CLI
seals the capture's exact bytes, their SHA-256 and optionally an Ed25519
signature over DSSE's pre-authentication encoding of those bytes; this
checks all three before a single fact is read.

**Why bytes and not a re-serialised object.** A signature is over bytes,
and Go and Python do not print a timestamp or a float the same way.
Verifying "decode, hash, check" needs no canonicalisation step in either
language, so there is no canonicalisation step to get wrong — the reason
DSSE exists, and the reason the payload travels base64-encoded.

**What a verified signature means**, precisely: the bundle has not
changed since whoever held that private key signed it. Not *who* that
was — the public key travels in the envelope. `captures.signed_by` stores
the key id so a reader can pin the ones they trust; docs/LIMITS.md says
this in the same words.

Every refusal names what failed and never quotes the payload: the
payload is a capture of an environment.
"""

import base64
import binascii
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from culprit_model.planes import Plane
from culprit_model.protocol import CaptureBundle
from pydantic import BaseModel, ConfigDict, ValidationError

#: Must match `capture.PayloadType` in the Go CLI byte for byte: it is
#: part of what is signed.
PAYLOAD_TYPE = "application/vnd.culprit.capture+json; version=1"


class Signature(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    keyid: str
    public_key: str
    sig: str


class Envelope(BaseModel):
    """The body of `POST /captures`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_type: str
    payload: str
    sha256: str
    signatures: tuple[Signature, ...] = ()


class EnvelopeRejected(ValueError):
    """An envelope that is altered, malformed, or not a CONFIGURED capture."""


class Opened(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    bundle: CaptureBundle
    digest: str
    #: Verified key ids, sorted and comma-joined; None when unsigned.
    signed_by: str | None


def _pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE's pre-authentication encoding, identical to `pae` in Go."""
    kind = payload_type.encode("utf-8")
    return b"DSSEv1 %d %s %d %s" % (len(kind), kind, len(payload), payload)


def key_id(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


def open_envelope(envelope: Envelope) -> Opened:
    if envelope.payload_type != PAYLOAD_TYPE:
        raise EnvelopeRejected("not a culprit capture (unexpected payload_type)")
    try:
        payload = base64.b64decode(envelope.payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeRejected("the payload is not valid base64") from exc

    digest = hashlib.sha256(payload).hexdigest()
    if digest != envelope.sha256:
        raise EnvelopeRejected(
            "the sha256 does not match the payload: the capture has been altered "
            "or corrupted since it was sealed"
        )

    verified: list[str] = []
    for index, signature in enumerate(envelope.signatures):
        try:
            public = base64.b64decode(signature.public_key, validate=True)
            sig = base64.b64decode(signature.sig, validate=True)
            key = Ed25519PublicKey.from_public_bytes(public)
            key.verify(sig, _pae(envelope.payload_type, payload))
        except (binascii.Error, ValueError, InvalidSignature) as exc:
            raise EnvelopeRejected(
                f"signatures.{index} does not verify: the capture has been altered "
                "since it was signed"
            ) from exc
        if key_id(public) != signature.keyid:
            raise EnvelopeRejected(f"signatures.{index}: keyid does not match its public key")
        verified.append(signature.keyid)

    try:
        raw = json.loads(payload)
        bundle = CaptureBundle.model_validate(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EnvelopeRejected("the payload is not JSON") from exc
    except ValidationError as exc:
        # Locations and error types only. Not pydantic's messages either:
        # a model validator's message can quote a subject, and a subject is
        # a fine place to hide a value (docs/LIMITS.md).
        where = "; ".join(
            ".".join(str(part) for part in error.get("loc", ())) + f" ({error.get('type')})"
            for error in exc.errors(include_url=False, include_context=False, include_input=False)
        )
        raise EnvelopeRejected(f"the payload is not a valid capture bundle: {where}") from exc

    if bundle.plane is not Plane.CONFIGURED:
        raise EnvelopeRejected(
            "POST /captures stores CONFIGURED captures; an INTENT capture belongs at "
            "POST /facts/captures"
        )
    return Opened(bundle=bundle, digest=digest, signed_by=",".join(sorted(verified)) or None)
