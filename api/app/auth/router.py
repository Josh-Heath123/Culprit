"""Self-service auth endpoints (Phase 16 rewrite): login, "who am I",
and changing your own password. Admin user-management lives in
app/auth/users_router.py, mounted separately at /users.
"""

from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from app.auth.dependencies import require_auth
from app.auth.repository import get_user_by_id, touch_last_login, update_password
from app.auth.schemas import ChangePasswordRequest, LoginRequest, LoginResponse, UserOut
from app.auth.security import (
    AuthenticatedUser,
    InvalidCredentials,
    WeakPassword,
    create_access_token,
    hash_password,
    validate_password,
    verify_credentials,
)
from app.db.models import User
from app.incidents.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])
logger = structlog.get_logger("auth")


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_auth_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.auth_session_factory
    async with session_factory() as session:
        yield session


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        disabled=user.disabled_at is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_auth_session),
) -> LoginResponse:
    try:
        user = await verify_credentials(session, body.username, body.password)
    except InvalidCredentials as exc:
        # The specific reason (unknown username / wrong password /
        # disabled) is logged (Phase 10: no silent 401s) but never
        # returned to the client — the response stays generic so a
        # caller can't use it to enumerate valid usernames or probe
        # which accounts are disabled.
        logger.warning("auth_login_failed", username=body.username, reason=str(exc))
        raise HTTPException(status_code=401, detail="invalid username or password") from exc

    await touch_last_login(session, user.id)
    logger.info("auth_login_succeeded", username=body.username)
    return LoginResponse(access_token=create_access_token(user), user=_user_out(user))


@router.get("/me", response_model=UserOut)
async def me(
    user: AuthenticatedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_read_session),
) -> UserOut:
    row = await get_user_by_id(session, user.id)
    if row is None:
        # Can't actually happen — require_auth already confirmed this
        # row exists and isn't disabled a moment ago — but satisfies the
        # type checker without asserting past a real (if theoretical)
        # race with a concurrent hard-delete.
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(row)


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    user: AuthenticatedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_auth_session),
) -> Response:
    row = await get_user_by_id(session, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")

    try:
        await verify_credentials(session, row.username, body.current_password)
    except InvalidCredentials as exc:
        logger.warning("auth_change_password_failed", username=row.username, reason=str(exc))
        raise HTTPException(status_code=401, detail="current password is incorrect") from exc

    try:
        validate_password(body.new_password, row.username)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Invalidates nothing else: tokens are short-lived (JWT_EXPIRY_MINUTES)
    # and there's no server-side session/refresh-token store to revoke
    # (docs/SELF_HOSTED_PLAN.md Phase 16, "Out of scope") — any token
    # issued before this change keeps working until it naturally expires.
    await update_password(session, row.id, hash_password(body.new_password))
    return Response(status_code=204)
