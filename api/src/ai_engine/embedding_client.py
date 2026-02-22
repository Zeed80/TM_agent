"""
Embedding Client — qwen3-embedding через Ollama CPU.

Работает на ollama-cpu (CUDA_VISIBLE_DEVICES="") — не конкурирует с LLM/VLM за VRAM.
AMD Ryzen 9 9900X справляется с batch-эмбеддингами на CPU.

Используется для:
  - Индексации документов в Qdrant (плотные векторы, dense)
  - Векторизации поисковых запросов в docs-search

Размерность: устанавливается в config.py (EMBEDDING_DIM).
Уточни после `ollama pull qwen3-embedding`:
    docker compose exec ollama-cpu ollama show qwen3-embedding --verbose
"""

import logging

import httpx

from src.app_settings import get_setting

logger = logging.getLogger(__name__)


def _embed_timeout() -> httpx.Timeout:
    t = get_setting("embedding_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Векторизует список текстов через qwen3-embedding (batch API).

    Использует Ollama /api/embed endpoint (поддерживает батчи).
    Оптимально для ETL-пайплайна (ingestion).

    Args:
        texts: Список строк для векторизации.

    Returns:
        Список float-векторов. Размерность = get_setting("embedding_dim").
    """
    if not texts:
        return []

    logger.debug(f"[Embedding] Векторизация {len(texts)} текстов")

    async with httpx.AsyncClient(timeout=_embed_timeout()) as client:
        response = await client.post(
            f"{get_setting('ollama_cpu_url')}/api/embed",
            json={
                "model": get_setting("embedding_model"),
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()

    embeddings: list[list[float]] = data["embeddings"]
    logger.debug(
        f"[Embedding] Готово: {len(embeddings)} векторов, "
        f"размерность={len(embeddings[0]) if embeddings else 0}"
    )
    return embeddings


async def embed_single(text: str) -> list[float]:
    """
    Векторизует один текст (поисковый запрос).

    Использует /api/embeddings (single-prompt endpoint).
    Чуть быстрее для единичных запросов в search-пайплайне.

    Args:
        text: Строка для векторизации.

    Returns:
        Float-вектор. Размерность = get_setting("embedding_dim").
    """
    logger.debug(f"[Embedding] Векторизация запроса: '{text[:80]}...'")

    async with httpx.AsyncClient(timeout=_embed_timeout()) as client:
        response = await client.post(
            f"{get_setting('ollama_cpu_url')}/api/embeddings",
            json={
                "model": get_setting("embedding_model"),
                "prompt": text,
            },
        )
        response.raise_for_status()
        data = response.json()

    embedding: list[float] = data["embedding"]
    logger.debug(f"[Embedding] Готово: размерность={len(embedding)}")
    return embedding
