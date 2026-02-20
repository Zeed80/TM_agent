"""
Роутер аутентификации и управления пользователями.

Endpoints:
  POST /api/v1/auth/login        — вход, получение JWT
  GET  /api/v1/auth/me           — текущий пользователь
  POST /api/v1/auth/users        — создание пользователя (admin)
  GET  /api/v1/auth/users        — список пользователей (admin)
  PUT  /api/v1/auth/users/{id}   — обновление (admin или self)
  DELETE /api/v1/auth/users/{id} — удаление (admin)
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth import (
    create_access_token,
    get_current_admin,
    get_current_user,
    hash_password,
    verify_password,
)
from src.config import settings
from src.db.postgres_client import postgres_client as _pg
from src.models.auth_models import (
    CreateUserRequest,
    LoginRequest,
    TokenResponse,
    UpdateUserRequest,
    UserPublic,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/login
# ─────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    """Аутентификация: username + password → JWT Bearer token."""
    rows = await _pg.execute_query(
        "SELECT id, username, full_name, email, role, is_active, password_hash, created_at "
        "FROM users WHERE username = :username",
        {"username": request.username},
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль.",
        )

    user = dict(rows[0])
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль.",
        )
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Учётная запись деактивирована.",
        )

    token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
    )
    user_public = UserPublic(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        email=user["email"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
    )
    logger.info(f"[Auth] Вход: {user['username']} (role={user['role']})")
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_hours * 3600,
        user=user_public,
    )


# ─────────────────────────────────────────────────────────────────────
# GET /api/v1/auth/me
# ─────────────────────────────────────────────────────────────────────
@router.get("/me", response_model=UserPublic)
async def me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    """Возвращает данные текущего аутентифицированного пользователя."""
    rows = await _pg.execute_query(
        "SELECT id, username, full_name, email, role, is_active, created_at "
        "FROM users WHERE id = :uid",
        {"uid": str(current_user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    return UserPublic(**dict(rows[0]))


# ─────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/users  (admin)
# ─────────────────────────────────────────────────────────────────────
@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user(
    request: CreateUserRequest,
    _admin: dict = Depends(get_current_admin),
) -> UserPublic:
    """Создание нового пользователя (только администратор)."""
    # Проверка уникальности username
    existing = await _pg.execute_query(
        "SELECT id FROM users WHERE username = :username",
        {"username": request.username},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Пользователь с именем '{request.username}' уже существует.",
        )

    hashed = hash_password(request.password)
    rows = await _pg.execute_query(
        """
        INSERT INTO users (username, full_name, email, password_hash, role)
        VALUES (:username, :full_name, :email, :password_hash, :role)
        RETURNING id, username, full_name, email, role, is_active, created_at
        """,
        {
            "username": request.username,
            "full_name": request.full_name,
            "email": str(request.email) if request.email else None,
            "password_hash": hashed,
            "role": request.role,
        },
    )
    logger.info(f"[Auth] Создан пользователь: {request.username} (role={request.role})")
    return UserPublic(**dict(rows[0]))


# ─────────────────────────────────────────────────────────────────────
# GET /api/v1/auth/users  (admin)
# ─────────────────────────────────────────────────────────────────────
@router.get("/users", response_model=list[UserPublic])
async def list_users(
    _admin: dict = Depends(get_current_admin),
) -> list[UserPublic]:
    """Список всех пользователей (только администратор)."""
    rows = await _pg.execute_query(
        "SELECT id, username, full_name, email, role, is_active, created_at "
        "FROM users ORDER BY created_at ASC",
    )
    return [UserPublic(**dict(row)) for row in rows]


# ─────────────────────────────────────────────────────────────────────
# PUT /api/v1/auth/users/{user_id}
# ─────────────────────────────────────────────────────────────────────
@router.put("/users/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: UUID,
    request: UpdateUserRequest,
    current_user: dict = Depends(get_current_user),
) -> UserPublic:
    """
    Обновление пользователя.
    Администратор может изменять любого, обычный пользователь — только себя.
    Обычный пользователь не может изменить свою роль.
    """
    is_admin = current_user["role"] == "admin"
    is_self = str(current_user["id"]) == str(user_id)

    if not is_admin and not is_self:
        raise HTTPException(status_code=403, detail="Нет прав для изменения этого пользователя.")
    if not is_admin and request.role is not None:
        raise HTTPException(status_code=403, detail="Изменение роли доступно только администратору.")
    if not is_admin and request.is_active is not None:
        raise HTTPException(status_code=403, detail="Деактивация доступна только администратору.")

    # Динамически строим SET-часть запроса
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict = {"uid": str(user_id)}

    if request.full_name is not None:
        set_parts.append("full_name = :full_name")
        params["full_name"] = request.full_name
    if request.email is not None:
        set_parts.append("email = :email")
        params["email"] = str(request.email)
    if request.password is not None:
        set_parts.append("password_hash = :password_hash")
        params["password_hash"] = hash_password(request.password)
    if request.role is not None:
        set_parts.append("role = :role")
        params["role"] = request.role
    if request.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = request.is_active

    rows = await _pg.execute_query(
        f"""
        UPDATE users
        SET {", ".join(set_parts)}
        WHERE id = :uid
        RETURNING id, username, full_name, email, role, is_active, created_at
        """,
        params,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    logger.info(f"[Auth] Обновлён пользователь: {user_id}")
    return UserPublic(**dict(rows[0]))


# ─────────────────────────────────────────────────────────────────────
# DELETE /api/v1/auth/users/{user_id}  (admin)
# ─────────────────────────────────────────────────────────────────────
@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    current_user: dict = Depends(get_current_admin),
) -> None:
    """Удаление пользователя (только администратор). Нельзя удалить себя."""
    if str(current_user["id"]) == str(user_id):
        raise HTTPException(status_code=400, detail="Нельзя удалить собственную учётную запись.")

    rows = await _pg.execute_query(
        "DELETE FROM users WHERE id = :uid RETURNING id",
        {"uid": str(user_id)},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    logger.info(f"[Auth] Удалён пользователь: {user_id}")
