"""
Роутер навыка enterprise-docs-search.

Endpoint: POST /skills/docs-search
Поток: Вопрос → Embedding → Hybrid Search (BM25+Dense, Qdrant) → Reranking → LLM (синтез)

Правило 3: Hybrid Search с Sparse (BM25) + Dense vectors + RRF Fusion.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.ai_engine import registry
from src.db.qdrant_client import qdrant_client
from src.models.sql_models import DocsSearchRequest, DocsSearchResponse

router = APIRouter(tags=["docs-search"])
logger = logging.getLogger(__name__)

_SYNTHESIS_SYSTEM_PROMPT = """Ты — заводской ИТР-ассистент. Отвечай на русском языке.
На основе фрагментов технической документации завода дай точный, структурированный ответ.
Цитируй конкретные цифры, таблицы и инструкции из документов.
Не добавляй информацию, которой нет в предоставленных фрагментах.
В конце укажи источники: название документа или файла.
Если подходящей информации нет — напиши: "В документации завода ответ на этот вопрос не найден."
"""


@router.post("/docs-search", response_model=DocsSearchResponse)
async def docs_search(request: DocsSearchRequest) -> DocsSearchResponse:
    """
    Навык enterprise-docs-search: Hybrid Search по Qdrant + Reranking + синтез ответа.

    Поддерживает поиск по: паспортам станков, инструкциям по эксплуатации,
    ГОСТам, деловой переписке, описаниям техпроцессов.

    Вызывается OpenClaw через curl:
        curl -s -X POST http://api:8000/skills/docs-search \\
          -H "Content-Type: application/json" \\
          -d '{"question": "Как настроить гитару 16К20 для дюймовой резьбы?"}'
    """
    logger.info(f"[docs-search] Запрос: '{request.question[:100]}'")

    # ── Шаг 1: Векторизация запроса ──────────────────────────────────
    try:
        dense_vector = await registry.embed_single(request.question)
    except Exception as exc:
        logger.error(f"[docs-search] Ошибка embedding: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка векторизации запроса: {exc}",
        )

    # ── Шаг 2: Hybrid Search (BM25 + Dense → RRF) ────────────────────
    # Правило 3: qdrant_client.hybrid_search использует double prefetch + Fusion.RRF
    filter_cond = None
    if request.source_filter:
        filter_cond = {"must": [{"key": "source_type", "match": {"value": request.source_filter}}]}

    try:
        candidates = await qdrant_client.hybrid_search(
            query_text=request.question,
            dense_vector=dense_vector,
            top_k=20,  # Берём 20 кандидатов перед reranking
            filter_conditions=filter_cond,
        )
    except Exception as exc:
        logger.error(f"[docs-search] Ошибка Qdrant Hybrid Search: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка поиска по документам: {exc}",
        )

    logger.info(f"[docs-search] Hybrid Search: найдено {len(candidates)} кандидатов")

    if not candidates:
        return DocsSearchResponse(
            answer="В документации завода ответ на этот вопрос не найден. "
                   "Возможно, соответствующие документы ещё не загружены в систему.",
            sources=[],
            chunks_found=0,
        )

    # ── Шаг 3: Reranking через qwen3-reranker ────────────────────────
    # Извлекаем тексты из payload для reranker
    candidate_texts = [
        point.payload.get("text", "") for point in candidates
    ]

    try:
        scores = await registry.rerank_batch(
            query=request.question,
            documents=candidate_texts,
        )
    except Exception as exc:
        logger.warning(
            f"[docs-search] Reranker недоступен, используем RRF-порядок: {exc}"
        )
        # Fallback: используем порядок из RRF (уже отсортированы)
        scores = [1.0 - i * 0.05 for i in range(len(candidates))]

    # Берём top_k лучших после reranking
    top_results = registry.sort_by_scores(
        items=candidates,
        scores=scores,
        top_k=request.top_k,
    )

    logger.info(
        f"[docs-search] После reranking: топ-{len(top_results)} из {len(candidates)}"
    )

    # ── Шаг 4: Синтез ответа через LLM ──────────────────────────────
    # Собираем контекст из найденных чанков (Правило 2: num_ctx=16384)
    context_parts = []
    sources_list = []

    for i, point in enumerate(top_results, start=1):
        payload = point.payload or {}
        text = payload.get("text", "")
        source = payload.get("source_file", payload.get("source", f"Документ {i}"))
        page = payload.get("page_number", "")

        source_label = source
        if page:
            source_label += f", стр. {page}"

        context_parts.append(f"[Источник {i}: {source_label}]\n{text}")
        sources_list.append({
            "text": text[:300],  # Обрезаем для компактности
            "source": source_label,
            "score": scores[candidates.index(point)] if point in candidates else 0.0,
            "drawing_number": payload.get("drawing_number"),
            "source_type": payload.get("source_type"),
        })

    context = "\n\n---\n\n".join(context_parts)

    synthesis_prompt = (
        f"Вопрос: {request.question}\n\n"
        f"Найденные фрагменты технической документации:\n\n{context}\n\n"
        "Сформулируй точный ответ на вопрос, используя данные из документов."
    )

    try:
        answer = await registry.generate(
            prompt=synthesis_prompt,
            system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
            temperature=0.1,
        )
    except Exception as exc:
        logger.error(f"[docs-search] Ошибка LLM при синтезе: {exc}")
        # Fallback: вернуть лучший чанк без синтеза
        answer = (
            f"Найдено {len(top_results)} фрагментов документации. "
            "Ошибка при синтезе ответа. Наиболее релевантный фрагмент:\n\n"
            + (candidate_texts[0][:1000] if candidate_texts else "Нет данных")
        )

    return DocsSearchResponse(
        answer=answer,
        sources=sources_list,
        chunks_found=len(candidates),
    )
