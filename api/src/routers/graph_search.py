"""
Роутер навыка enterprise-graph-search.

Endpoint: POST /skills/graph-search
Поток: Вопрос → LLM (Text-to-Cypher) → Neo4j → LLM (синтез ответа)

Anti-hallucination:
  1. temperature=0.0 при генерации Cypher
  2. Pydantic-валидация сгенерированного Cypher (нет деструктивных операций)
  3. Если Neo4j вернул пустой результат — LLM честно сообщает об этом
  4. Если LLM сгенерировал невалидный Cypher — возвращаем ошибку без выполнения
"""

import json
import logging

from fastapi import APIRouter, HTTPException

from src.ai_engine import llm_client
from src.ai_engine.prompts.text_to_cypher import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from src.db.neo4j_client import neo4j_client
from src.models.graph_models import (
    GeneratedCypherQuery,
    GraphSearchRequest,
    GraphSearchResponse,
)

router = APIRouter(tags=["graph-search"])
logger = logging.getLogger(__name__)

# Системный промпт для финального синтеза ответа (после выполнения Cypher)
_SYNTHESIS_SYSTEM_PROMPT = """Ты — заводской ИТР-ассистент. Отвечай на русском языке.
На основе данных из производственной базы (Neo4j) составь чёткий, структурированный ответ.
Не придумывай данных, которых нет в результатах запроса.
Если данные есть — используй конкретные значения: названия, номера, размеры.
Если данных нет — напиши: "В базе данных завода информация по этому запросу отсутствует."
"""


@router.post("/graph-search", response_model=GraphSearchResponse)
async def graph_search(request: GraphSearchRequest) -> GraphSearchResponse:
    """
    Навык enterprise-graph-search: Text-to-Cypher → Neo4j → синтез ответа.

    Вызывается OpenClaw через curl:
        curl -s -X POST http://api:8000/skills/graph-search \\
          -H "Content-Type: application/json" \\
          -d '{"question": "Покажи маршрут изготовления детали 123-456"}'
    """
    logger.info(f"[graph-search] Запрос: '{request.question[:100]}'")

    # ── Шаг 1: Генерация Cypher через LLM ────────────────────────────
    user_prompt = USER_PROMPT_TEMPLATE.format(question=request.question)
    if request.use_few_shot:
        user_prompt = FEW_SHOT_EXAMPLES + "\n\n" + user_prompt

    try:
        raw_json = await llm_client.generate_json(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.error(f"[graph-search] Ошибка LLM при генерации Cypher: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка LLM при генерации Cypher-запроса: {exc}",
        )

    # ── Шаг 2: Pydantic-валидация сгенерированного Cypher ────────────
    try:
        parsed = json.loads(raw_json)
        generated = GeneratedCypherQuery(**parsed)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(f"[graph-search] Невалидный JSON или Cypher от LLM: {exc}\nRaw: {raw_json}")
        raise HTTPException(
            status_code=422,
            detail=(
                f"LLM вернул невалидный Cypher-запрос. "
                f"Попробуй переформулировать вопрос. Детали: {exc}"
            ),
        )

    logger.info(
        f"[graph-search] Сгенерированный Cypher: {generated.cypher[:200]}"
    )

    # ── Шаг 3: Выполнение в Neo4j ────────────────────────────────────
    try:
        records = await neo4j_client.run_query(generated.cypher)
    except Exception as exc:
        logger.error(f"[graph-search] Ошибка Neo4j при выполнении: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка выполнения запроса к графу: {exc}",
        )

    logger.info(f"[graph-search] Neo4j вернул {len(records)} записей")

    # ── Шаг 4: Синтез ответа ─────────────────────────────────────────
    if records:
        records_text = json.dumps(records, ensure_ascii=False, indent=2)
        synthesis_prompt = (
            f"Вопрос пользователя: {request.question}\n\n"
            f"Данные из производственного графа (Neo4j):\n{records_text}\n\n"
            "Сформулируй чёткий ответ на вопрос на основе этих данных."
        )
    else:
        synthesis_prompt = (
            f"Вопрос пользователя: {request.question}\n\n"
            "Запрос к производственному графу (Neo4j) не вернул результатов.\n"
            "Сообщи пользователю, что данные не найдены в базе, "
            "и предложи уточнить номер чертежа или название детали."
        )

    try:
        answer = await llm_client.generate(
            prompt=synthesis_prompt,
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            temperature=0.1,  # Чуть больше 0 для естественного языка
        )
    except Exception as exc:
        logger.error(f"[graph-search] Ошибка LLM при синтезе ответа: {exc}")
        # Если синтез не удался — вернуть сырые данные
        answer = (
            f"Найдено записей: {len(records)}. "
            "Ошибка при формировании ответа. Сырые данные: "
            + json.dumps(records[:3], ensure_ascii=False)
        )

    return GraphSearchResponse(
        answer=answer,
        raw_results=records,
        cypher_used=generated.cypher,
        records_count=len(records),
    )
