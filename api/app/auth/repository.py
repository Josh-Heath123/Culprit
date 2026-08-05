"""DB access for the `users` table (Phase 16) — the auth-service role for
writes, whatever engine the caller passes for reads (app/auth/router.py
wires auth-service for everything under /auth and /users; app/auth/
dependencies.py's require_auth wires api-reader for its own read-only
disabled-check — see that module's own comment on why it doesn't reuse
this module's write-capable engine).
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    return (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.execute(select(User).order_by(User.username))).scalars().all())


async def create_user(
    session: AsyncSession, *, username: str, password_hash: str, role: str
) -> User:
    user = User(username=username, password_hash=password_hash, role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession, user_id: UUID, *, role: str | None = None, disabled: bool | None = None
) -> User | None:
    user = await get_user_by_id(session, user_id)
    if user is None:
        return None
    if role is not None:
        user.role = role
    if disabled is not None:
        user.disabled_at = datetime.now(UTC) if disabled else None
    await session.commit()
    await session.refresh(user)
    return user


async def update_password(session: AsyncSession, user_id: UUID, password_hash: str) -> bool:
    user = await get_user_by_id(session, user_id)
    if user is None:
        return False
    user.password_hash = password_hash
    await session.commit()
    return True


async def touch_last_login(session: AsyncSession, user_id: UUID) -> None:
    user = await get_user_by_id(session, user_id)
    if user is not None:
        user.last_login_at = datetime.now(UTC)
        await session.commit()
