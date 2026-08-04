"""Minimal JWT session auth for the dashboard API (Phase 9 — built here
only as a short prerequisite for Phase 10's self-observability, per
CLAUDE.md: Phase 10 needs a real auth-failure path to instrument, and
there wasn't one yet). This covers login + token verification only; the
full dedicated Phase 9 pass docs/IMPLEMENTATION_PLAN.md describes —
DB-role-enforcement tests, a frontend login UI — is still real future
work, not done here.
"""

import contextlib
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.auth.config import (
    JWT_ALGORITHM,
    JWT_EXPIRY_MINUTES,
    JWT_SECRET_KEY,
    OPERATOR_PASSWORD_HASH,
    OPERATOR_USERNAME,
)

_hasher = PasswordHasher()


class InvalidCredentials(Exception):
    """Carries the *specific* reason (unknown username vs. wrong
    password) for structured logging (Phase 10) — the HTTP layer
    (app/auth/router.py) deliberately collapses this to one generic
    message in the response so a client can't distinguish the two."""


def verify_credentials(username: str, password: str) -> None:
    if username != OPERATOR_USERNAME:
        # Still run the hasher on a wrong-username path so a wrong
        # username and a wrong password take roughly the same time —
        # cheap defense against username enumeration via response timing.
        with contextlib.suppress(VerifyMismatchError):
            _hasher.verify(OPERATOR_PASSWORD_HASH, password)
        raise InvalidCredentials("unknown username")
    try:
        _hasher.verify(OPERATOR_PASSWORD_HASH, password)
    except VerifyMismatchError as exc:
        raise InvalidCredentials("wrong password") from exc


def create_access_token(username: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=JWT_EXPIRY_MINUTES)
    payload = {"sub": username, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Raises jwt.PyJWTError (ExpiredSignatureError/InvalidTokenError)
    on failure — left uncaught here; app/auth/dependencies.py is what
    translates those into an HTTP response and a structured log entry."""
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    return payload["sub"]
