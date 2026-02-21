"""
Pydantic-модели для чат-сессий и сообщений.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Создание новой чат-сессии."""

    title: str = Field(default="Новый чат", max_length=500)


class UpdateSessionRequest(BaseModel):
    """Переименование сессии."""

    title: str = Field(..., min_length=1, max_length=500)


class SessionPublic(BaseModel):
    """Публичные данные сессии."""

    id: UUID
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message_count: int = 0


class SendMessageRequest(BaseModel):
    """Отправка сообщения в чат (SSE-стриминг ответа)."""

    content: str = Field(..., min_length=1)


class ChatMessagePublic(BaseModel):
    """Сообщение в истории чата."""

    id: UUID
    session_id: UUID
    role: str
    content: str | None = None
    tool_name: str | None = None
    tool_input: str | None = None
    tool_result: str | None = None
    created_at: datetime | None = None
