"""
Qdrant Async Client — Hybrid Search (BM25 Sparse + Dense Vectors).

Правило 3: Коллекция обязательно создаётся с sparse_vectors_config (BM25).
Поиск: двойной prefetch (dense + sparse) → слияние через Fusion.RRF.

Архитектура Hybrid Search:
    Query
      ├── Dense prefetch: qwen3-embedding → cosine similarity → топ-20
      └── Sparse prefetch: fastembed BM25 → sparse dot product → топ-20
            ↓
        RRF Fusion (Reciprocal Rank Fusion) → топ-5 объединённых
            ↓
        Reranker (qwen3-reranker на CPU) → финальный топ-5

Инициализация коллекции: вызови `await qdrant_client.ensure_collection()` при старте.
"""

import logging

from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    NamedSparseVector,
    NamedVector,
    Prefetch,
    ScoredPoint,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from src.app_settings import get_setting
from src.config import settings

logger = logging.getLogger(__name__)

# Инициализация BM25-модели из fastembed (Правило 3)
# "Qdrant/bm25" — официальная BM25-модель для Qdrant, работает на CPU
# Загружается один раз при старте приложения (~50MB)
_bm25_model = SparseTextEmbedding("Qdrant/bm25")


def _compute_bm25(texts: list[str]) -> list[SparseVector]:
    """
    Вычисляет BM25 sparse векторы для списка текстов.
    Использует fastembed SparseTextEmbedding("Qdrant/bm25").
    """
    embeddings = list(_bm25_model.embed(texts))
    return [
        SparseVector(indices=list(emb.indices), values=list(emb.values))
        for emb in embeddings
    ]


def _compute_bm25_single(text: str) -> SparseVector:
    """Вычисляет BM25 для одного текста (поисковый запрос)."""
    return _compute_bm25([text])[0]


class QdrantClientWrapper:
    """
    Обёртка над AsyncQdrantClient с методами для Hybrid Search.

    Правило 3: все операции с векторами используют как dense, так и sparse.
    """

    def __init__(self) -> None:
        self._client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        """Подключиться к Qdrant. Вызывается в lifespan."""
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        logger.info(f"[Qdrant] Подключено: {settings.qdrant_host}:{settings.qdrant_port}")

    async def close(self) -> None:
        """Закрыть соединение."""
        if self._client:
            await self._client.close()
            logger.info("[Qdrant] Соединение закрыто")

    async def ensure_collection(self) -> None:
        """
        Создать коллекцию с Sparse + Dense векторами, если не существует.

        Правило 3: sparse_vectors_config с BM25 обязателен.
        Вектора:
          - "dense": qwen3-embedding, cosine distance, размер = EMBEDDING_DIM
          - "bm25": fastembed BM25, sparse, on_disk=False (in-memory для скорости)
        """
        collection_name = get_setting("qdrant_collection")

        collections = await self._client.get_collections()
        existing = [c.name for c in collections.collections]

        if collection_name in existing:
            logger.info(f"[Qdrant] Коллекция '{collection_name}' уже существует")
            return

        dense_dim = get_setting("embedding_dim")
        dense_name = get_setting("qdrant_dense_vector_name")
        sparse_name = get_setting("qdrant_sparse_vector_name")
        logger.info(
            f"[Qdrant] Создание коллекции '{collection_name}' "
            f"(dense_dim={dense_dim}, sparse=BM25)"
        )

        await self._client.create_collection(
            collection_name=collection_name,
            # Правило 3: Dense vectors (qwen3-embedding)
            vectors_config={
                dense_name: VectorParams(
                    size=dense_dim,
                    distance=Distance.COSINE,
                    on_disk=False,  # Держим в RAM для скорости поиска
                )
            },
            # Правило 3: Sparse vectors (BM25) — ОБЯЗАТЕЛЬНО
            sparse_vectors_config={
                sparse_name: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)  # in-memory BM25-индекс
                )
            },
        )

        logger.info(f"[Qdrant] Коллекция '{collection_name}' создана успешно")

    async def upsert_document(
        self,
        chunk_id: str,
        text: str,
        dense_vector: list[float],
        metadata: dict,
    ) -> None:
        """
        Добавить или обновить документ в Qdrant.

        Автоматически вычисляет BM25 sparse вектор из text.

        Args:
            chunk_id: Уникальный ID чанка (UUID-строка).
            text: Исходный текст чанка (сохраняется в payload для reranker).
            dense_vector: float-вектор от qwen3-embedding.
            metadata: Дополнительные метаданные (source, page, drawing_number...).
        """
        sparse_vector = _compute_bm25_single(text)

        payload = {
            "text": text,
            **metadata,
        }

        coll = get_setting("qdrant_collection")
        dense_name = get_setting("qdrant_dense_vector_name")
        sparse_name = get_setting("qdrant_sparse_vector_name")
        await self._client.upsert(
            collection_name=coll,
            points=[
                {
                    "id": chunk_id,
                    "vectors": {
                        dense_name: dense_vector,
                        sparse_name: {
                            "indices": sparse_vector.indices,
                            "values": sparse_vector.values,
                        },
                    },
                    "payload": payload,
                }
            ],
        )

    async def upsert_batch(
        self,
        chunks: list[dict],
    ) -> None:
        """
        Batch upsert для ETL-пайплайна.

        Args:
            chunks: Список словарей с ключами:
                - id: str (UUID)
                - text: str
                - dense_vector: list[float]
                - metadata: dict
        """
        if not chunks:
            return

        # Вычисляем BM25 для всех текстов батчем (эффективнее поштучно)
        texts = [c["text"] for c in chunks]
        sparse_vectors = _compute_bm25(texts)

        coll = get_setting("qdrant_collection")
        dense_name = get_setting("qdrant_dense_vector_name")
        sparse_name = get_setting("qdrant_sparse_vector_name")
        points = []
        for chunk, sparse_vec in zip(chunks, sparse_vectors):
            points.append(
                {
                    "id": chunk["id"],
                    "vectors": {
                        dense_name: chunk["dense_vector"],
                        sparse_name: {
                            "indices": list(sparse_vec.indices),
                            "values": list(sparse_vec.values),
                        },
                    },
                    "payload": {
                        "text": chunk["text"],
                        **chunk.get("metadata", {}),
                    },
                }
            )

        await self._client.upsert(
            collection_name=coll,
            points=points,
        )
        logger.debug(f"[Qdrant] Upsert {len(points)} документов")

    async def hybrid_search(
        self,
        query_text: str,
        dense_vector: list[float],
        top_k: int | None = None,
        filter_conditions: dict | None = None,
    ) -> list[ScoredPoint]:
        """
        Hybrid Search: BM25 Sparse + Dense → RRF Fusion.

        Правило 3: Двойной prefetch + Fusion.RRF.

        Шаги:
          1. Prefetch dense: косинусное сходство → settings.qdrant_prefetch_limit кандидатов
          2. Prefetch sparse (BM25): → settings.qdrant_prefetch_limit кандидатов
          3. RRF Fusion объединяет оба списка в единый рейтинг
          4. Возвращает top_k лучших (до reranking)

        Args:
            query_text: Исходный текст запроса (для BM25).
            dense_vector: Вектор запроса от qwen3-embedding.
            top_k: Количество результатов. По умолчанию settings.qdrant_prefetch_limit.
            filter_conditions: Фильтр по metadata (опционально).

        Returns:
            Список ScoredPoint с payload (включая "text" для reranker).
        """
        prefetch_limit = get_setting("qdrant_prefetch_limit")
        if top_k is None:
            top_k = prefetch_limit

        sparse_vector = _compute_bm25_single(query_text)
        dense_name = get_setting("qdrant_dense_vector_name")
        sparse_name = get_setting("qdrant_sparse_vector_name")
        coll = get_setting("qdrant_collection")

        # Правило 3: Двойной prefetch + RRF
        prefetch = [
            # Dense prefetch (семантическое сходство)
            Prefetch(
                query=NamedVector(
                    name=dense_name,
                    vector=dense_vector,
                ),
                limit=prefetch_limit,
                filter=filter_conditions,
            ),
            # Sparse prefetch (BM25 keyword matching)
            Prefetch(
                query=NamedSparseVector(
                    name=sparse_name,
                    vector=sparse_vector,
                ),
                limit=prefetch_limit,
                filter=filter_conditions,
            ),
        ]

        results = await self._client.query_points(
            collection_name=coll,
            prefetch=prefetch,
            query=Fusion.RRF,  # Reciprocal Rank Fusion — объединяет оба списка
            limit=top_k,
            with_payload=True,
        )

        logger.debug(
            f"[Qdrant] Hybrid Search: запрос='{query_text[:60]}', "
            f"результатов={len(results.points)}"
        )
        return results.points

    async def health_check(self) -> bool:
        """Проверка доступности Qdrant."""
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            logger.error(f"[Qdrant] Health check failed: {exc}")
            return False


# Глобальный синглтон
qdrant_client = QdrantClientWrapper()
