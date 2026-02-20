"""
Инициализация коллекции Qdrant (Sparse + Dense).

Правило 3: коллекция создаётся с обязательным sparse_vectors_config (BM25).

Запуск: make init-qdrant
  или: docker compose --profile ingestion run --rm ingestion python -m src.setup_qdrant
"""

import asyncio
import logging

from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("=== Инициализация коллекции Qdrant ===")
    logger.info(f"  Хост: {settings.qdrant_host}:{settings.qdrant_port}")
    logger.info(f"  Коллекция: {settings.qdrant_collection}")
    logger.info(f"  Dense dim: {settings.embedding_dim}")

    client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    try:
        # Проверяем существующие коллекции
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]

        if settings.qdrant_collection in existing:
            logger.info(f"Коллекция '{settings.qdrant_collection}' уже существует")
            info = await client.get_collection(settings.qdrant_collection)
            logger.info(f"  Точек в коллекции: {info.points_count}")
            return

        # Правило 3: Создаём с Sparse (BM25) + Dense vectors
        logger.info("Создание коллекции с Hybrid Search конфигурацией (BM25 + Dense)...")
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            # Dense vectors — семантическое сходство (qwen3-embedding)
            vectors_config={
                settings.qdrant_dense_vector_name: VectorParams(
                    size=settings.embedding_dim,
                    distance=Distance.COSINE,
                    on_disk=False,
                )
            },
            # Sparse vectors — BM25 keyword matching (fastembed)
            # Правило 3: ОБЯЗАТЕЛЬНО для полноценного Hybrid Search
            sparse_vectors_config={
                settings.qdrant_sparse_vector_name: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)  # in-memory для скорости
                )
            },
        )

        logger.info(f"✓ Коллекция '{settings.qdrant_collection}' создана")
        logger.info(f"  Dense vector: '{settings.qdrant_dense_vector_name}' (dim={settings.embedding_dim}, cosine)")
        logger.info(f"  Sparse vector: '{settings.qdrant_sparse_vector_name}' (BM25, in-memory)")
        logger.info("")
        logger.info("Следующий шаг — загрузка документов:")
        logger.info("  make ingest-pdf        # Паспорта станков, ГОСТы, письма")
        logger.info("  make ingest-blueprints # Чертежи через VLM")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
