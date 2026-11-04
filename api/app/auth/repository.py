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


class LastAdminError(Exception):
    """The change would leave no enabled admin (Phase 32 part 2)."""


def _is_active_admin(user: User) -> bool:
    return user.role == "admin" and user.disabled_at is None


async def update_user(
    session: AsyncSession, user_id: UUID, *, role: str | None = None, disabled: bool | None = None
) -> User | None:
    """Change a user's role or disabled state — never leaving no admin.

    Demoting or disabling the last enabled admin locks every admin out,
    with no way back short of `just create-user` on the host (found by
    Phase 31.2's truth pass). So when the change would remove an active
    admin, every active-admin row is locked (SELECT ... FOR UPDATE) and
    counted in the same transaction as the change. Two admins demoting
    each other at the same moment: the second waits on the first's lock,
    re-reads, sees one admin left, and is refused.
    """
    user = await get_user_by_id(session, user_id)
    if user is None:
        return None
    removes_admin = _is_active_admin(user) and (
        (role is not None and role != "admin") or disabled is True
    )
    if removes_admin:
        active = (
            (
                await session.execute(
                    select(User.id)
                    .where(User.role == "admin", User.disabled_at.is_(None))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        # The lock may have waited on another transaction; decide on what
        # is committed now, not on what was read before it.
        await session.refresh(user)
        if _is_active_admin(user) and len(active) <= 1 and user.id in active:
            await session.rollback()
            raise LastAdminError
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
