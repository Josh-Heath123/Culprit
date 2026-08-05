"""Tests for app/auth/security.py against a real, migrated Postgres
container (see api/tests/conftest.py) — Phase 16 rewrote verify_credentials
to look a user up in the database, so a mocked/substituted hash (the old
approach) can no longer exercise the real path. Truncates `users` before
each test rather than relying on a specific starting state: local runs
always have api/.env's real OPERATOR_USERNAME/OPERATOR_PASSWORD_HASH
backfilled by the migration, CI runs (which no longer set those, per
Phase 16 step 10) don't — this file's tests must pass either way.
"""

import time
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import jwt
import pytest
import pytest_asyncio
from app.auth.config import JWT_ALGORITHM, JWT_SECRET_KEY
from app.auth.repository import create_user
from app.auth.security import (
    MIN_PASSWORD_LENGTH,
    InvalidCredentials,
    WeakPassword,
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password,
    verify_credentials,
)
from app.db.models import User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_PASSWORD = "correct-horse-battery-staple"


@pytest_asyncio.fixture
async def session(migrated_database_url: str, db_engine: AsyncEngine, role_database_url):
    async with db_engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))

    auth_url = role_database_url("auth-service", "AUTH_SERVICE_DB_PASSWORD")
    engine = create_async_engine(auth_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def active_user(session: AsyncSession) -> User:
    return await create_user(
        session, username="test-operator", password_hash=hash_password(_PASSWORD), role="admin"
    )


async def test_verify_credentials_accepts_the_real_password(
    session: AsyncSession, active_user: User
) -> None:
    user = await verify_credentials(session, active_user.username, _PASSWORD)
    assert user.id == active_user.id


async def test_verify_credentials_rejects_wrong_password(
    session: AsyncSession, active_user: User
) -> None:
    with pytest.raises(InvalidCredentials, match="wrong password"):
        await verify_credentials(session, active_user.username, "not-the-password")


async def test_verify_credentials_rejects_unknown_username(session: AsyncSession) -> None:
    with pytest.raises(InvalidCredentials, match="unknown username"):
        await verify_credentials(session, "someone-else", _PASSWORD)


async def test_verify_credentials_rejects_disabled_user_even_with_correct_password(
    session: AsyncSession,
) -> None:
    user = await create_user(
        session, username="disabled-user", password_hash=hash_password(_PASSWORD), role="member"
    )
    user.disabled_at = datetime.now(UTC)
    await session.commit()

    with pytest.raises(InvalidCredentials, match="disabled"):
        await verify_credentials(session, user.username, _PASSWORD)


async def test_unknown_username_path_still_calls_the_hasher(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural test of the timing-attack defence, not a statistical
    one (a real timing-parity test would be flaky in CI) — asserts that
    an unknown username still exercises the password hasher exactly like
    a real verify would, rather than short-circuiting before it."""
    import app.auth.security as security_module

    spy = MagicMock(wraps=security_module._hasher)
    monkeypatch.setattr(security_module, "_hasher", spy)

    with pytest.raises(InvalidCredentials, match="unknown username"):
        await verify_credentials(session, "nobody-by-this-name", _PASSWORD)

    spy.verify.assert_called_once()


def test_access_token_round_trips() -> None:
    user = User(id=uuid.uuid4(), username="test-operator", password_hash="unused", role="admin")
    token = create_access_token(user)
    payload = decode_access_token(token)
    assert payload.sub == "test-operator"
    assert payload.uid == user.id
    assert payload.role == "admin"


def test_expired_token_is_rejected() -> None:
    expired = jwt.encode(
        {
            "sub": "test-operator",
            "uid": str(uuid.uuid4()),
            "role": "admin",
            "exp": time.time() - 60,
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired)


def test_token_signed_with_a_different_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": "test-operator",
            "uid": str(uuid.uuid4()),
            "role": "admin",
            "exp": time.time() + 3600,
        },
        "wrong-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_validate_password_rejects_too_short() -> None:
    with pytest.raises(WeakPassword, match="at least"):
        validate_password("short1", "someuser")


def test_validate_password_rejects_matching_username() -> None:
    with pytest.raises(WeakPassword, match="username"):
        validate_password("same-as-username", "same-as-username")


def test_validate_password_accepts_a_reasonable_password() -> None:
    validate_password("a" * MIN_PASSWORD_LENGTH, "someuser")
