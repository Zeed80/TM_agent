"""
PostgreSQL Async Client.

Управляет пулом соединений через asyncpg + SQLAlchemy 2 async.
Предоставляет методы для:
  - inventory-sql навыка (Text-to-SQL)
  - auth/chat роутеров (внутренние запросы без LLM)

Методы:
  execute_select(sql, params)      — только SELECT (LLM-generated), с валидацией
  execute_query(sql, params)       — любой SQL, returning rows (trusted internal SQL)
  execute_write(sql, params)       — INSERT/UPDATE/DELETE без RETURNING (rowcount)
  health_check()                   — проверка соединения
"""

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)

# Белый список разрешённых SQL-команд (только SELECT) — для LLM-запросов
_ALLOWED_SQL_PATTERN = re.compile(
    r"^\s*SELECT\b",
    re.IGNORECASE | re.MULTILINE,
)

# Паттерны запрещённых команд (дополнительная защита от LLM-инъекций)
_FORBIDDEN_SQL_PATTERNS = [
    re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.IGNORECASE),
    re.compile(r"--"),
    re.compile(r"/\*.*?\*/", re.DOTALL),
]


def validate_sql(sql: str) -> None:
    """
    Проверяет, что LLM-сгенерированный SQL-запрос безопасен (только SELECT).
    НЕ используется для внутренних доверенных запросов (auth, chat и т.д.).
    """
    if not _ALLOWED_SQL_PATTERN.match(sql.strip()):
        raise ValueError(
            f"SQL-запрос должен начинаться с SELECT. Получено: '{sql[:100]}'"
        )
    for pattern in _FORBIDDEN_SQL_PATTERNS:
        if pattern.search(sql):
            raise ValueError(
                f"SQL-запрос содержит запрещённую команду: '{pattern.pattern}'"
            )


class PostgresClient:
    """
    Асинхронный клиент PostgreSQL.

    Поддерживает два формата параметров:
      - Позиционные: sql с $1,$2... и params=list  (исторический формат для LLM SQL)
      - Именованные: sql с :name... и params=dict   (внутренние доверенные запросы)
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: sessionmaker | None = None

    async def connect(self) -> None:
        """Создать пул соединений. Вызывается в lifespan."""
        self._engine = create_async_engine(
            settings.postgres_dsn,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("[PostgreSQL] Пул соединений создан")

    async def close(self) -> None:
        """Закрыть пул соединений."""
        if self._engine:
            await self._engine.dispose()
            logger.info("[PostgreSQL] Соединения закрыты")

    async def execute_select(
        self,
        sql: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Выполнить SELECT-запрос (LLM-generated) с валидацией безопасности.

        Для внутренних доверенных запросов используй execute_query().

        Args:
            sql: SELECT-запрос. Параметры: $1,$2... (list) или :name (dict).
            params: Список или словарь значений.

        Returns:
            Список словарей (колонка → значение).
        """
        validate_sql(sql)
        return await self._run_query(sql, params)

    async def execute_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Выполнить произвольный SQL с именованными параметрами (:name).
        Используется для внутренних доверенных операций (auth, chat, files).

        Поддерживает SELECT и INSERT/UPDATE/DELETE ... RETURNING.

        Args:
            sql: SQL-запрос с :name параметрами.
            params: Словарь параметров.

        Returns:
            Список строк (пустой список если нет RETURNING).
        """
        return await self._run_query(sql, params or {})

    async def execute_write(
        self,
        sql: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> int:
        """
        Выполнить INSERT/UPDATE/DELETE без RETURNING (только для ingestion пайплайна).

        Returns:
            Количество затронутых строк.
        """
        if self._engine is None:
            raise RuntimeError("PostgreSQL не подключён. Вызови await connect().")

        converted_sql, named_params = _normalize_params(sql, params)

        async with self._session_factory() as session:
            result = await session.execute(text(converted_sql), named_params)
            await session.commit()

        rowcount: int = result.rowcount
        logger.debug(f"[PostgreSQL] Write-запрос: {rowcount} строк")
        return rowcount

    async def health_check(self) -> bool:
        """Проверка доступности PostgreSQL."""
        try:
            await self._run_query("SELECT 1 AS ok", {})
            return True
        except Exception as exc:
            logger.error(f"[PostgreSQL] Health check failed: {exc}")
            return False

    async def _run_query(
        self,
        sql: str,
        params: list[Any] | dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Внутренний метод выполнения запроса и возврата строк."""
        if self._engine is None:
            raise RuntimeError("PostgreSQL не подключён. Вызови await connect().")

        converted_sql, named_params = _normalize_params(sql, params)

        async with self._session_factory() as session:
            result = await session.execute(text(converted_sql), named_params)
            await session.commit()
            try:
                rows = result.mappings().all()
                records = [dict(row) for row in rows]
            except Exception:
                records = []

        logger.debug(f"[PostgreSQL] Запрос вернул {len(records)} строк")
        return records


def _normalize_params(
    sql: str,
    params: list[Any] | dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """
    Нормализует параметры:
      - dict → передаём как есть (SQLAlchemy text :name style)
      - list → конвертируем $N в :pN style
      - None → пустой dict
    """
    if params is None:
        return sql, {}
    if isinstance(params, dict):
        return sql, params
    # Позиционные параметры ($1, $2, ...)
    named_params: dict[str, Any] = {}
    converted = sql
    for i, value in enumerate(params, start=1):
        converted = converted.replace(f"${i}", f":p{i}")
        named_params[f"p{i}"] = value
    return converted, named_params


# Глобальный синглтон
postgres_client = PostgresClient()
