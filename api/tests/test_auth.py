"""Unit tests for app/auth/security.py — no HTTP layer, no DB, pure
credential/token logic. app/auth/dependencies.py and router.py are thin
FastAPI wiring around this and aren't separately unit-tested, same
convention as the rest of this codebase (e.g. worker/app/anomaly/job.py's
I/O wiring isn't unit-tested, only the pure logic it calls).

Credential tests use a locally-generated username/password/hash, not the
real operator credential from .env — otherwise these tests would be
coupled to a real secret and break the moment it's ever rotated.
"""

import time

import app.auth.security as auth_security
import jwt
import pytest
from app.auth.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.auth.security import (
    InvalidCredentials,
    create_access_token,
    decode_access_token,
    verify_credentials,
)
from argon2 import PasswordHasher

_TEST_USERNAME = "test-operator"
_TEST_PASSWORD = "correct-horse-battery-staple"
_TEST_PASSWORD_HASH = PasswordHasher().hash(_TEST_PASSWORD)


@pytest.fixture(autouse=True)
def _fake_operator_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    # security.py does `from app.auth.config import OPERATOR_USERNAME, ...`,
    # which binds its own local names at import time — patching
    # app.auth.config's attributes afterward wouldn't touch those already-
    # bound names, so the patch has to target app.auth.security directly.
    monkeypatch.setattr(auth_security, "OPERATOR_USERNAME", _TEST_USERNAME)
    monkeypatch.setattr(auth_security, "OPERATOR_PASSWORD_HASH", _TEST_PASSWORD_HASH)


def test_verify_credentials_accepts_the_real_password() -> None:
    verify_credentials(_TEST_USERNAME, _TEST_PASSWORD)


def test_verify_credentials_rejects_wrong_password() -> None:
    with pytest.raises(InvalidCredentials, match="wrong password"):
        verify_credentials(_TEST_USERNAME, "not-the-password")


def test_verify_credentials_rejects_unknown_username() -> None:
    with pytest.raises(InvalidCredentials, match="unknown username"):
        verify_credentials("someone-else", _TEST_PASSWORD)


def test_access_token_round_trips() -> None:
    token = create_access_token(_TEST_USERNAME)
    assert decode_access_token(token) == _TEST_USERNAME


def test_expired_token_is_rejected() -> None:
    # A token minted with exp in the past, signed with the real secret —
    # exercises decode_access_token's own expiry check, not a mock.
    expired = jwt.encode(
        {"sub": _TEST_USERNAME, "exp": time.time() - 60},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_token_signed_with_a_different_secret_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": _TEST_USERNAME, "exp": time.time() + 3600}, "wrong-secret", algorithm="HS256"
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)
