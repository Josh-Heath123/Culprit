"""The Python half of the capture envelope — against what Go actually seals.

`shared/tests/capture_envelope_conformance.json` is a real envelope,
sealed and Ed25519-signed by `cli/internal/capture` with a fixed test key
(`TestEnvelopeConformance` there keeps it byte-stable). If this file
cannot verify it, `POST /captures` cannot accept anything the CLI
produces, and the failure would otherwise first appear in production on
the first upload.

No database here: `app/model/envelope.py` and `check_grants` are pure.
The storage path is `test_captures_api.py`.
"""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from app.model.captures import UngrantedFact, check_grants
from app.model.envelope import Envelope, EnvelopeRejected, open_envelope
from culprit_model.planes import Plane

FIXTURE = Path(__file__).parents[2] / "shared" / "tests" / "capture_envelope_conformance.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _with_payload(envelope: dict, mutate) -> dict:
    """The fixture with its payload rewritten and the digest recomputed —
    i.e. a tamperer who knows to fix the sha256 but cannot re-sign."""
    raw = json.loads(base64.b64decode(envelope["payload"]))
    mutate(raw)
    payload = json.dumps(raw).encode()
    return {
        **envelope,
        "payload": base64.b64encode(payload).decode(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_python_verifies_what_go_signed() -> None:
    opened = open_envelope(Envelope(**_fixture()))
    assert opened.bundle.plane is Plane.CONFIGURED
    assert opened.bundle.environment == "staging"
    assert opened.signed_by is not None and len(opened.signed_by) == 16
    assert {grant.capability for grant in opened.bundle.grants} >= {
        "config.read.names",
        "config.read.values",
    }
    assert opened.bundle.refused[0].capability == "net.dns.resolve"
    check_grants(opened.bundle)


def test_an_unsigned_envelope_opens_with_no_signer() -> None:
    envelope = _fixture()
    envelope["signatures"] = []
    assert open_envelope(Envelope(**envelope)).signed_by is None


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda e: {**e, "sha256": "0" + e["sha256"][1:]}, id="digest edited"),
        pytest.param(
            lambda e: {**e, "payload": base64.b64encode(b'{"plane":"CONFIGURED"}').decode()},
            id="payload replaced, digest left",
        ),
        pytest.param(
            # The edit that matters most: drop what the capture was refused,
            # so it claims to have looked at things it was never allowed to.
            lambda e: _with_payload(e, lambda raw: raw.pop("refused")),
            id="refusals dropped, digest fixed, signature not",
        ),
        pytest.param(lambda e: {**e, "payload_type": "application/json"}, id="payload type"),
    ],
)
def test_an_altered_envelope_is_refused(tamper) -> None:
    with pytest.raises(EnvelopeRejected):
        open_envelope(Envelope(**tamper(_fixture())))


def test_an_intent_capture_is_refused_here() -> None:
    envelope = _with_payload(_fixture(), lambda raw: raw.update(plane="INTENT"))
    envelope["signatures"] = []
    with pytest.raises(EnvelopeRejected):
        open_envelope(Envelope(**envelope))


def test_a_refusal_never_quotes_the_payload() -> None:
    secret = "postgresql://u:hunter2-envelope@db/orders"
    envelope = _with_payload(
        _fixture(), lambda raw: raw["facts"].append({"subject": secret, "plane": "CONFIGURED"})
    )
    envelope["signatures"] = []
    with pytest.raises(EnvelopeRejected) as caught:
        open_envelope(Envelope(**envelope))
    assert "hunter2" not in str(caught.value)


# --- grants -----------------------------------------------------------


def _opened_with(mutate):
    envelope = _with_payload(_fixture(), mutate)
    envelope["signatures"] = []
    return open_envelope(Envelope(**envelope)).bundle


@pytest.mark.parametrize(
    ("mutate", "rule"),
    [
        pytest.param(
            lambda raw: raw["facts"][2].update(grant_ref="config.read.values:orders-api/OTHER"),
            "not on its grant's allowlist",
            id="a value under another key's grant",
        ),
        pytest.param(
            lambda raw: raw["grants"].pop(1),
            "does not list",
            id="a value under a grant the capture does not hold",
        ),
        pytest.param(
            lambda raw: raw["facts"][2].update(grant_ref="config.read.names"),
            "not its own key's",
            id="a config value under the names grant",
        ),
        pytest.param(
            lambda raw: raw["facts"][3].update(grant_ref="db.rows.read:orders"),
            "does not list",
            id="a digest under a grant nobody gave",
        ),
    ],
)
def test_every_value_must_name_a_grant_the_capture_held(mutate, rule: str) -> None:
    """docs/LIMITS.md recorded, until Phase 30, that "nothing validates
    that the grant it names is real". These are that validation."""
    bundle = _opened_with(mutate)
    with pytest.raises(UngrantedFact, match=rule) as caught:
        check_grants(bundle)
    assert "LOG_LEVEL" not in str(caught.value), "a refusal names the index, not the subject"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda raw: raw["refused"][0].update(reason="could not reach postgresql://u:hunter2-e@db/x"),
            id="a DSN in a refusal reason",
        ),
        pytest.param(
            lambda raw: raw["meta"].update(note="token sk-ABCDEFGHIJKLMNOPQRSTUVWX"),
            id="a provider key in meta",
        ),
    ],
)
def test_hand_written_free_text_cannot_carry_a_credential(mutate) -> None:
    """The phase audit's tamper: edit the text, re-hash, upload. Refused,
    and the refusal does not quote what it refused."""
    envelope = _with_payload(_fixture(), mutate)
    envelope["signatures"] = []
    with pytest.raises(EnvelopeRejected) as caught:
        open_envelope(Envelope(**envelope))
    assert "hunter2" not in str(caught.value)
    assert "sk-ABCDEF" not in str(caught.value)
