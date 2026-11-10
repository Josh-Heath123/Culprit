"""The signing contract, held to shared/tests/agent_signing_conformance.json
— the Python half of cli/internal/agentauth's test (Phase 33 part 2).

Every case behaves as written; and, Ed25519 being deterministic, Python
signs every accepted case to exactly the fixture's signature from the
named seed, so the canonical form is the same in both languages, not
merely compatible.
"""

import base64
import hashlib
import json
from pathlib import Path

from app.agents import signing
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

FIXTURE = json.loads(
    (Path(__file__).parents[2] / "shared" / "tests" / "agent_signing_conformance.json").read_text(
        encoding="utf-8"
    )
)


def private_key(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label.encode()).digest())


def _request(case: dict) -> signing.SignedRequest:
    return signing.SignedRequest(
        method=case["method"],
        path=case["path"],
        body=case["body"].encode("utf-8"),
        timestamp=case["timestamp"],
        nonce=case["nonce"],
        agent_id=case["agent_id"],
    )


def test_the_scheme_and_skew_match_the_fixture() -> None:
    assert FIXTURE["scheme"] == signing.SCHEME
    assert FIXTURE["max_skew_seconds"] == signing.MAX_SKEW_SECONDS


def test_every_signing_case_behaves_as_written() -> None:
    assert len(FIXTURE["cases"]) >= 10
    outcomes = set()
    for case in FIXTURE["cases"]:
        stored = FIXTURE["keys"].get(case["agent_id"])
        key = (
            signing.AgentKey(base64.b64decode(stored["public_key"]), stored["revoked"])
            if stored
            else None
        )
        seen = frozenset(case["seen_nonces"])
        accepted = signing.decide(
            key, _request(case), case["signature"], case["now"], seen.__contains__
        )
        assert accepted == (case["expect"] == "accept"), case["why"]
        outcomes.add(accepted)
        if case.get("canonical"):
            assert signing.canonical(_request(case)).decode() == case["canonical"], case["why"]
    assert outcomes == {True, False}


def test_python_reproduces_the_fixtures_signatures() -> None:
    for case in FIXTURE["cases"]:
        if case["expect"] != "accept":
            continue
        key = private_key(FIXTURE["keys"][case["signed_by"]]["seed_sha256_of"])
        signature = base64.b64encode(key.sign(signing.canonical(_request(case)))).decode()
        assert signature == case["signature"], case["why"]


def test_the_public_keys_are_the_seeds_own() -> None:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    for stored in FIXTURE["keys"].values():
        public = (
            private_key(stored["seed_sha256_of"])
            .public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
        assert base64.b64encode(public).decode() == stored["public_key"]
