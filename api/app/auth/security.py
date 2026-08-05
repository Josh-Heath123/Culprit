"""JWT session auth (Phase 9, rewritten for Phase 16's `users` table).

Covers credential verification, password hashing/policy, and token
issuance/decoding. HTTP wiring is app/auth/router.py; the per-request
auth dependency (with its own DB-backed disabled-check) is
app/auth/dependencies.py.
"""

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import JWT_ALGORITHM, JWT_EXPIRY_MINUTES, JWT_SECRET_KEY
from app.auth.repository import get_user_by_username
from app.db.models import User

_hasher = PasswordHasher()

#: Verified on every unknown-username login attempt so that path costs
#: the same as a real wrong-password check (see verify_credentials) --
#: a fixed, module-level hash rather than deriving one from a real user
#: row, since there may be zero rows (a fresh install) or the row that
#: would have matched may not exist at all.
_DUMMY_HASH = _hasher.hash("dummy-password-only-used-for-timing-parity")

#: Password policy (docs/SELF_HOSTED_PLAN.md Phase 16, step 7): a
#: minimum length and "not the same as your own username," nothing more
#: — complexity rules (must contain a digit/symbol/etc.) make chosen
#: passwords *worse* on average (predictable substitutions, forced
#: reuse elsewhere), and this codebase isn't going to pretend otherwise
#: just because that's the more familiar-looking rule to enforce.
MIN_PASSWORD_LENGTH = 12


class InvalidCredentials(Exception):
    """Carries the *specific* reason (unknown username / wrong password /
    disabled) for structured logging (Phase 10) — the HTTP layer
    (app/auth/router.py) deliberately collapses this to one generic
    message in the response so a client can't distinguish any of them.
    """


class WeakPassword(Exception):
    """Carries the specific policy violation for the caller to surface —
    unlike InvalidCredentials, there's no enumeration/timing concern
    here, so the reason is fine to return directly to the client."""


@dataclass(frozen=True)
class TokenPayload:
    sub: str
    uid: UUID
    role: str


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    username: str
    role: str


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def validate_password(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password == username:
        raise WeakPassword("password must not be the same as the username")


async def verify_credentials(session: AsyncSession, username: str, password: str) -> User:
    user = await get_user_by_username(session, username)
    if user is None:
        # Still run the hasher on an unknown-username path so a wrong
        # username and a wrong password take roughly the same time —
        # cheap defense against username enumeration via response timing.
        with contextlib.suppress(VerifyMismatchError):
            _hasher.verify(_DUMMY_HASH, password)
        raise InvalidCredentials("unknown username")

    try:
        _hasher.verify(user.password_hash, password)
    except VerifyMismatchError as exc:
        raise InvalidCredentials("wrong password") from exc

    # Checked *after* the real password verify, not before -- a disabled
    # user's password check still runs, so a disabled account doesn't
    # respond any faster than an active one and leak its own status via
    # timing on top of the generic 401 both cases already share.
    if user.disabled_at is not None:
        raise InvalidCredentials("disabled")

    return user


def create_access_token(user: User) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=JWT_EXPIRY_MINUTES)
    # `sub` stays the username, not swapped for the uid -- dropping it
    # would invalidate every token issued before this change for no
    # benefit (docs/SELF_HOSTED_PLAN.md Phase 16's API surface section).
    payload = {"sub": user.username, "uid": str(user.id), "role": user.role, "exp": expires_at}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    """Raises jwt.PyJWTError (ExpiredSignatureError/InvalidTokenError)
    on failure — left uncaught here; app/auth/dependencies.py is what
    translates those into an HTTP response and a structured log entry."""
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    return TokenPayload(sub=payload["sub"], uid=UUID(payload["uid"]), role=payload["role"])
