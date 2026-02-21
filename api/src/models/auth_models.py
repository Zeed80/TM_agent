"""
Pydantic-модели для аутентификации и управления пользователями.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Запрос на вход: логин и пароль."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserPublic(BaseModel):
    """Публичные данные пользователя (без password_hash)."""

    id: UUID
    username: str
    full_name: str | None = None
    email: str | None = None
    role: str
    is_active: bool = True
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    """Ответ с JWT и данными пользователя."""

    access_token: str
    expires_in: int  # секунды
    user: UserPublic


class CreateUserRequest(BaseModel):
    """Создание пользователя (admin)."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    full_name: str | None = None
    email: EmailStr | None = None
    role: str = Field(default="user", pattern="^(admin|user)$")


class UpdateUserRequest(BaseModel):
    """Обновление пользователя (частичное)."""

    full_name: str | None = None
    email: EmailStr | None = None
    password: str | None = None
    role: str | None = None
    is_active: bool | None = None
