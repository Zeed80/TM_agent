"""
Reranker Client — qwen3-reranker через Ollama CPU.

Reranker — cross-encoder модель: принимает пару (query, document)
и возвращает числовой score релевантности [0.0 — 1.0].

Используется в docs-search для улучшения качества поиска:
  1. Qdrant Hybrid Search (BM25 + Dense) → топ-20 кандидатов
  2. Reranker переранжирует кандидатов → топ-5 лучших

Qwen3-Reranker через Ollama работает как генеративная модель:
  - Вход: специальный промпт с query и document
  - Выход: токены "yes"/"no" с вероятностями (или числовой score)
  - Мы парсим logprobs или используем score из ответа

Fallback: если Ollama не возвращает logprobs,
используем semantic similarity через logit "1"/"0" в первом токене.
"""

import logging
import re

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

_RERANK_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=settings.reranker_timeout,
    write=settings.reranker_timeout,
    pool=5.0,
)

# Промпт-шаблон для Qwen3-Reranker (cross-encoder формат)
_RERANK_PROMPT_TEMPLATE = (
    "Given a query and a document, determine if the document is relevant to the query.\n"
    "Answer with a relevance score between 0.0 and 1.0, where:\n"
    "  1.0 = highly relevant\n"
    "  0.0 = not relevant\n\n"
    "Query: {query}\n\n"
    "Document:\n{document}\n\n"
    "Relevance score (respond with only a decimal number between 0.0 and 1.0):"
)


def _parse_score(text: str) -> float:
    """
    Парсит числовой score из ответа модели.
    Ожидаем строку вида "0.87" или "0.9" или "yes"/"no".
    """
    text = text.strip().lower()

    # Прямое соответствие "yes"/"no"
    if text.startswith("yes"):
        return 0.9
    if text.startswith("no"):
        return 0.1

    # Ищем первое числовое значение в ответе
    numbers = re.findall(r"\b(0\.\d+|1\.0|1)\b", text)
    if numbers:
        return min(1.0, max(0.0, float(numbers[0])))

    # Если модель вернула неожиданный ответ — нейтральный score
    logger.warning(f"[Reranker] Не удалось распарсить score из: '{text[:100]}', используем 0.5")
    return 0.5


async def rerank_single(query: str, document: str) -> float:
    """
    Вычисляет score релевантности для одной пары (query, document).

    Args:
        query: Поисковый запрос пользователя.
        document: Текст кандидата из Qdrant.

    Returns:
        float [0.0 — 1.0]. Чем выше, тем более релевантен документ.
    """
    prompt = _RERANK_PROMPT_TEMPLATE.format(
        query=query,
        document=document[:2000],  # Ограничиваем документ для скорости
    )

    async with httpx.AsyncClient(timeout=_RERANK_TIMEOUT) as client:
        response = await client.post(
            f"{settings.ollama_cpu_url}/api/generate",
            json={
                "model": settings.reranker_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 10,  # Ожидаем очень короткий ответ (только score)
                    "top_k": 1,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

    raw_response: str = data.get("response", "").strip()
    score = _parse_score(raw_response)
    logger.debug(f"[Reranker] score={score:.3f} для query='{query[:50]}...'")
    return score


async def rerank_batch(
    query: str,
    documents: list[str],
) -> list[float]:
    """
    Переранжирует список документов относительно запроса.

    Выполняется последовательно (CPU-модель, нет смысла параллелить
    из-за ограничений памяти ollama-cpu при большом батче).

    Args:
        query: Поисковый запрос.
        documents: Список текстов кандидатов.

    Returns:
        Список scores в том же порядке, что documents.
        Пример: [0.92, 0.45, 0.88, 0.12, 0.76]
    """
    if not documents:
        return []

    logger.info(f"[Reranker] Переранжирование {len(documents)} документов для query='{query[:60]}'")

    scores: list[float] = []
    for i, doc in enumerate(documents):
        score = await rerank_single(query, doc)
        scores.append(score)
        logger.debug(f"[Reranker] Документ {i + 1}/{len(documents)}: score={score:.3f}")

    logger.info(f"[Reranker] Готово. Лучший score: {max(scores):.3f}")
    return scores


def sort_by_scores(
    items: list,
    scores: list[float],
    top_k: int | None = None,
) -> list:
    """
    Сортирует элементы по убыванию score и возвращает top_k лучших.

    Args:
        items: Список объектов (например, ScoredPoint из Qdrant).
        scores: Список scores (тот же порядок, что items).
        top_k: Количество возвращаемых элементов. None = все.

    Returns:
        Отсортированный список элементов.
    """
    paired = sorted(zip(scores, items), key=lambda x: x[0], reverse=True)
    if top_k is not None:
        paired = paired[:top_k]
    return [item for _, item in paired]
