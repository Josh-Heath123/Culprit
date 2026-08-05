"""Admin user management (Phase 16) — mounted at /users in
api/app/main.py, gated by require_admin (not the plain require_auth
/auth/* and /services use) — see app/auth/dependencies.py.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import Response

from app.auth.repository import (
    create_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    update_password,
)
from app.auth.repository import update_user as repo_update_user
from app.auth.router import _user_out
from app.auth.schemas import (
    CreateUserRequest,
    PatchUserRequest,
    ResetPasswordRequest,
    UserOut,
    UsersOut,
)
from app.auth.security import WeakPassword, hash_password, validate_password

router = APIRouter(prefix="/users", tags=["users"])


async def get_write_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.auth_session_factory
    async with session_factory() as session:
        yield session


@router.get("", response_model=UsersOut)
async def list_users_endpoint(session: AsyncSession = Depends(get_write_session)) -> UsersOut:
    return UsersOut(items=[_user_out(u) for u in await list_users(session)])


@router.post("", response_model=UserOut, status_code=201)
async def create_user_endpoint(
    body: CreateUserRequest, session: AsyncSession = Depends(get_write_session)
) -> UserOut:
    if await get_user_by_username(session, body.username) is not None:
        raise HTTPException(status_code=409, detail=f"username {body.username!r} already exists")
    try:
        validate_password(body.password, body.username)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = await create_user(
        session, username=body.username, password_hash=hash_password(body.password), role=body.role
    )
    return _user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def patch_user_endpoint(
    user_id: UUID, body: PatchUserRequest, session: AsyncSession = Depends(get_write_session)
) -> UserOut:
    fields = body.model_dump(exclude_unset=True)
    user = await repo_update_user(
        session, user_id, role=fields.get("role"), disabled=fields.get("disabled")
    )
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _user_out(user)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password_endpoint(
    user_id: UUID, body: ResetPasswordRequest, session: AsyncSession = Depends(get_write_session)
) -> Response:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    try:
        validate_password(body.new_password, user.username)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await update_password(session, user_id, hash_password(body.new_password))
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
async def delete_user_endpoint(
    user_id: UUID, session: AsyncSession = Depends(get_write_session)
) -> Response:
    user = await repo_update_user(session, user_id, disabled=True)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return Response(status_code=204)
