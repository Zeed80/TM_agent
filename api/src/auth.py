"""
Утилиты аутентификации — JWT + bcrypt.

Используется в:
  - routers/auth_router.py — выдача токенов
  - Dependency get_current_user — валидация Bearer токена во всех защищённых эндпоинтах
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID  # noqa: F401 — используется в аннотациях

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import settings
from src.db.postgres_client import postgres_client

logger = logging.getLogger(__name__)

# bcrypt ограничивает пароль 72 байтами
_BCRYPT_MAX_PASSWORD_BYTES = 72

# ── Bearer-схема (не auto_error — чтобы сами формировали 401) ─────────
_bearer_scheme = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────────────────────────
# Утилиты паролей (bcrypt напрямую — без passlib из-за несовместимости с bcrypt 4.1+)
# ─────────────────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Создаёт bcrypt-хэш пароля."""
    pwd_bytes = plain_password.encode("utf-8")[: _BCRYPT_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль против bcrypt-хэша."""
    try:
        pwd_bytes = plain_password.encode("utf-8")[: _BCRYPT_MAX_PASSWORD_BYTES]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────
# Утилиты JWT
# ─────────────────────────────────────────────────────────────────────

def create_access_token(
    user_id: UUID,
    username: str,
    role: str,
) -> str:
    """
    Создаёт подписанный JWT-токен.

    Payload:
        sub  — user_id (str)
        usr  — username
        rol  — role ('admin' | 'user')
        exp  — время истечения
    """
    expire = datetime.now(tz=timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user_id),
        "usr": username,
        "rol": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Декодирует и валидирует JWT.

    Returns:
        Декодированный payload.

    Raises:
        HTTPException 401 при невалидном/истёкшем токене.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Невалидный или истёкший токен. Выполните вход заново.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return payload
    except JWTError as exc:
        logger.warning(f"[Auth] JWT decode error: {exc}")
        raise credentials_exception


# ─────────────────────────────────────────────────────────────────────
# FastAPI Dependencies
# ─────────────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI dependency — извлекает текущего пользователя из Bearer-токена.

    Returns:
        dict с полями: id, username, full_name, email, role, is_active
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация. Передайте Bearer-токен.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload["sub"]

    # Загружаем актуальные данные из БД (чтобы учесть is_active, смену роли)
    rows = await postgres_client.execute_query(
        "SELECT id, username, full_name, email, role, is_active "
        "FROM users WHERE id = :uid",
        {"uid": user_id},
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден.",
        )

    user = dict(rows[0])
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Учётная запись деактивирована.",
        )
    return user


async def get_current_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """FastAPI dependency — проверяет что пользователь является администратором."""
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права администратора.",
        )
    return current_user
