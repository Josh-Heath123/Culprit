from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Role = Literal["admin", "member"]


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: UUID
    username: str
    role: Role
    disabled: bool
    last_login_at: datetime | None
    created_at: datetime | None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UsersOut(BaseModel):
    items: list[UserOut]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: Role = "member"


class PatchUserRequest(BaseModel):
    """All fields optional; only the ones actually present in the
    request body are applied (same exclude_unset convention as
    app/registry/schemas.py's ServicePatch) — a PATCH that omits `role`
    must leave it alone, not reset it to a default."""

    role: Role | None = None
    disabled: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str
