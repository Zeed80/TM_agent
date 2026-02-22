"""
Роутер навыка inventory-sql-search.

Endpoint: POST /skills/inventory-sql
Поток: Вопрос → LLM (Text-to-SQL) → Pydantic-валидация → PostgreSQL → LLM (синтез)

Безопасность:
  1. Только SELECT разрешён (validate_sql в Pydantic-модели + postgres_client)
  2. Параметризованные запросы ($1, $2...) — никогда не конкатенируем строки
  3. temperature=0.0 для детерминированной генерации SQL
"""

import json
import logging

from fastapi import APIRouter, HTTPException

from src.ai_engine import registry
from src.ai_engine.prompts.text_to_sql import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from src.db.postgres_client import postgres_client
from src.models.sql_models import (
    GeneratedSQLQuery,
    InventorySearchRequest,
    InventorySearchResponse,
)

router = APIRouter(tags=["inventory-sql"])
logger = logging.getLogger(__name__)

_SYNTHESIS_SYSTEM_PROMPT = """Ты — заводской ИТР-ассистент. Отвечай на русском языке.
На основе данных из складской системы (PostgreSQL) дай точный ответ.
Указывай конкретные количества, единицы измерения и местоположения на складе.
Если остаток нулевой или отрицательный — явно предупреди об отсутствии позиции.
Если данных нет — напиши: "Позиция не найдена в базе данных склада."
"""


@router.post("/inventory-sql", response_model=InventorySearchResponse)
async def inventory_sql_search(request: InventorySearchRequest) -> InventorySearchResponse:
    """
    Навык inventory-sql-search: Text-to-SQL → PostgreSQL → синтез ответа.

    Поддерживает запросы по: инструменту, металлам, полимерам,
    складским остаткам, зарезервированным позициям.

    Вызывается OpenClaw через curl:
        curl -s -X POST http://api:8000/skills/inventory-sql \\
          -H "Content-Type: application/json" \\
          -d '{"question": "Сколько полиамида 6 есть на складе?"}'
    """
    logger.info(f"[inventory-sql] Запрос: '{request.question[:100]}'")

    # ── Шаг 1: Генерация SQL через LLM ───────────────────────────────
    user_prompt = USER_PROMPT_TEMPLATE.format(question=request.question)
    if request.use_few_shot:
        user_prompt = FEW_SHOT_EXAMPLES + "\n\n" + user_prompt

    try:
        raw_json = await registry.generate_json_llm(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.error(f"[inventory-sql] Ошибка LLM при генерации SQL: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка LLM при генерации SQL-запроса: {exc}",
        )

    # ── Шаг 2: Pydantic-валидация SQL (только SELECT, нет DML) ───────
    try:
        parsed = json.loads(raw_json)
        generated = GeneratedSQLQuery(**parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(
            f"[inventory-sql] Невалидный JSON или SQL от LLM: {exc}\n"
            f"Raw: {raw_json[:500]}"
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"LLM вернул невалидный SQL-запрос. "
                f"Попробуй переформулировать вопрос. Детали: {exc}"
            ),
        )

    logger.info(
        f"[inventory-sql] Сгенерированный SQL: {generated.sql[:200]}, "
        f"params: {generated.params}"
    )

    # ── Шаг 3: Выполнение в PostgreSQL ───────────────────────────────
    try:
        rows = await postgres_client.execute_select(
            sql=generated.sql,
            params=generated.params,
        )
    except ValueError as exc:
        # validate_sql поднял ошибку — SQL небезопасен
        logger.error(f"[inventory-sql] Небезопасный SQL: {exc}")
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[inventory-sql] Ошибка PostgreSQL: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка выполнения запроса к складу: {exc}",
        )

    logger.info(f"[inventory-sql] PostgreSQL вернул {len(rows)} строк")

    # ── Шаг 4: Синтез ответа ─────────────────────────────────────────
    if rows:
        rows_text = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
        synthesis_prompt = (
            f"Вопрос пользователя: {request.question}\n\n"
            f"Данные из складской системы (PostgreSQL):\n{rows_text}\n\n"
            "Сформулируй чёткий ответ о наличии на складе."
        )
    else:
        synthesis_prompt = (
            f"Вопрос пользователя: {request.question}\n\n"
            "Запрос к складской базе данных не вернул результатов.\n"
            "Сообщи пользователю, что позиция не найдена, "
            "и предложи проверить название или марку материала."
        )

    try:
        answer = await registry.generate(
            prompt=synthesis_prompt,
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            temperature=0.1,
        )
    except Exception as exc:
        logger.error(f"[inventory-sql] Ошибка LLM при синтезе: {exc}")
        answer = (
            f"Найдено строк: {len(rows)}. "
            "Ошибка при формировании ответа. "
            + (json.dumps(rows[:3], ensure_ascii=False, default=str) if rows else "Данных нет.")
        )

    return InventorySearchResponse(
        answer=answer,
        raw_results=rows,
        sql_used=generated.sql,
        rows_count=len(rows),
    )
