"""
Neo4j Async Client.

Управляет пулом соединений к Neo4j через официальный async-драйвер.
Предоставляет методы для выполнения Cypher-запросов из навыков OpenClaw.

Инициализация: вызови `await neo4j_client.connect()` в lifespan FastAPI.
Завершение: вызови `await neo4j_client.close()` при shutdown.
"""

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from src.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Асинхронный клиент Neo4j.

    Паттерн использования (в роутерах):
        from src.db.neo4j_client import neo4j_client

        results = await neo4j_client.run_query(
            "MATCH (p:Part {drawing_number: $dn}) RETURN p",
            {"dn": "123-456"}
        )
    """

    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Открыть соединение с Neo4j. Вызывается в lifespan."""
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=10,
            connection_timeout=30.0,
        )
        # Проверяем соединение
        await self._driver.verify_connectivity()
        logger.info(f"[Neo4j] Подключено: {settings.neo4j_uri}")

    async def close(self) -> None:
        """Закрыть соединение. Вызывается при shutdown FastAPI."""
        if self._driver:
            await self._driver.close()
            logger.info("[Neo4j] Соединение закрыто")

    async def run_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]:
        """
        Выполнить Cypher-запрос и вернуть список записей.

        Args:
            cypher: Cypher-запрос. Параметры через $param_name.
            params: Словарь параметров. НИКОГДА не подставляй значения напрямую.
            database: Имя базы данных Neo4j.

        Returns:
            Список словарей. Каждый словарь — одна строка результата.
            Пример: [{"part_name": "Втулка", "machine": "DMG CMX 600V"}, ...]
        """
        if self._driver is None:
            raise RuntimeError("Neo4j не подключён. Вызови await connect() при старте.")

        params = params or {}

        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, params)
            records = await result.data()

        logger.debug(f"[Neo4j] Запрос вернул {len(records)} записей")
        return records

    async def run_write_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]:
        """
        Выполнить Cypher с правами записи (используется в ingestion).

        Выполняется в write-транзакции для корректного разрешения конфликтов.
        """
        if self._driver is None:
            raise RuntimeError("Neo4j не подключён.")

        params = params or {}

        async def _write_tx(tx: AsyncSession) -> list[dict[str, Any]]:
            result = await tx.run(cypher, params)
            return await result.data()

        async with self._driver.session(database=database) as session:
            records: list[dict[str, Any]] = await session.execute_write(_write_tx)

        logger.debug(f"[Neo4j] Write-запрос выполнен, записей: {len(records)}")
        return records

    async def run_batch_write(
        self,
        operations: list[tuple[str, dict[str, Any]]],
        database: str = "neo4j",
    ) -> None:
        """
        Выполнить несколько write-запросов в одной транзакции.

        Используется в ingestion для атомарной записи техпроцессов
        (создать деталь + создать операции + создать связи — всё или ничего).

        Args:
            operations: Список кортежей (cypher, params).
        """
        if self._driver is None:
            raise RuntimeError("Neo4j не подключён.")

        async def _batch_tx(tx: AsyncSession) -> None:
            for cypher, params in operations:
                await tx.run(cypher, params)

        async with self._driver.session(database=database) as session:
            await session.execute_write(_batch_tx)

        logger.debug(f"[Neo4j] Batch write: {len(operations)} операций выполнено")

    async def health_check(self) -> bool:
        """Проверка доступности Neo4j."""
        try:
            await self.run_query("RETURN 1 AS ok")
            return True
        except Exception as exc:
            logger.error(f"[Neo4j] Health check failed: {exc}")
            return False


# Глобальный синглтон — используется во всех роутерах
neo4j_client = Neo4jClient()
