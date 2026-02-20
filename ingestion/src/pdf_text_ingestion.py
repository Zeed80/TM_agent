"""
PDF/DOCX/EML Text Ingestion → Qdrant (Hybrid Search).

Читает текстовые документы из documents/manuals/, documents/gosts/, documents/emails/,
разбивает на чанки, создаёт Dense (qwen3-embedding) + Sparse (BM25 fastembed) векторы
и загружает в Qdrant.

Правило 3: оба вектора (dense + sparse) загружаются для Hybrid Search.

Запуск: make ingest-pdf
"""

import asyncio
import base64
import email
import logging
import re
import uuid
from email import policy as email_policy
from pathlib import Path
from typing import Iterator

import aiofiles
import httpx
from fastembed import SparseTextEmbedding
from pypdf import PdfReader
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from tqdm import tqdm

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Директории с документами
MANUALS_DIR = Path(settings.documents_dir) / "manuals"
GOSTS_DIR = Path(settings.documents_dir) / "gosts"
EMAILS_DIR = Path(settings.documents_dir) / "emails"

# BM25 модель (Правило 3)
_bm25_model = SparseTextEmbedding("Qdrant/bm25")


# ── Текстовые утилиты ─────────────────────────────────────────────────────────

def extract_text_from_pdf(filepath: Path) -> str:
    """Извлекает текст из PDF (с поддержкой кириллицы)."""
    reader = PdfReader(filepath)
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return "\n".join(pages_text)


def extract_text_from_docx(filepath: Path) -> str:
    """Извлекает текст из DOCX."""
    if DocxDocument is None:
        logger.warning("python-docx не установлен, пропускаю DOCX")
        return ""
    doc = DocxDocument(filepath)
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(paragraphs)


def extract_text_from_eml(filepath: Path) -> str:
    """Извлекает текст из .eml файла (деловое письмо)."""
    with open(filepath, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email_policy.default)

    subject = str(msg.get("subject", ""))
    from_addr = str(msg.get("from", ""))
    date = str(msg.get("date", ""))

    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body_parts.append(payload.decode(charset, errors="replace"))

    header = f"От: {from_addr}\nДата: {date}\nТема: {subject}\n\n"
    return header + "\n".join(body_parts)


def split_into_chunks(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """
    Разбивает текст на чанки с перекрытием.

    Пытается делать разрыв на границах предложений/абзацев.
    """
    if not text.strip():
        return []

    # Нормализуем пробелы
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        # Ищем естественную границу разрыва (конец предложения/абзаца)
        if end < text_len:
            # Ищем ближайший разрыв абзаца или конец предложения
            boundary = text.rfind("\n\n", start, end)
            if boundary == -1 or (end - boundary) > chunk_size // 2:
                boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 1

        chunk = text[start:end].strip()
        if chunk and len(chunk) > 50:  # Пропускаем слишком короткие чанки
            chunks.append(chunk)

        start = end - overlap if end < text_len else text_len

    return chunks


# ── Векторизация ──────────────────────────────────────────────────────────────

async def embed_texts_batch(texts: list[str]) -> list[list[float]]:
    """Векторизует батч текстов через qwen3-embedding (Ollama CPU)."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=settings.embedding_timeout,
            write=settings.embedding_timeout,
            pool=5.0,
        )
    ) as client:
        response = await client.post(
            f"{settings.ollama_cpu_url}/api/embed",
            json={
                "model": settings.embedding_model,
                "input": texts,
            },
        )
        response.raise_for_status()
        return response.json()["embeddings"]


def compute_bm25_batch(texts: list[str]) -> list[SparseVector]:
    """Вычисляет BM25 sparse векторы (Правило 3)."""
    embeddings = list(_bm25_model.embed(texts))
    return [
        SparseVector(indices=list(e.indices), values=list(e.values))
        for e in embeddings
    ]


# ── Qdrant Upsert ─────────────────────────────────────────────────────────────

async def ensure_qdrant_collection(client: AsyncQdrantClient) -> None:
    """Создаёт коллекцию если не существует. Правило 3: Sparse + Dense."""
    collections = await client.get_collections()
    existing = [c.name for c in collections.collections]

    if settings.qdrant_collection in existing:
        logger.info(f"Коллекция '{settings.qdrant_collection}' уже существует")
        return

    logger.info(f"Создание коллекции '{settings.qdrant_collection}'...")
    await client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={
            settings.qdrant_dense_vector_name: VectorParams(
                size=settings.embedding_dim,
                distance=Distance.COSINE,
            )
        },
        sparse_vectors_config={
            settings.qdrant_sparse_vector_name: SparseVectorParams(
                index=SparseIndexParams(on_disk=False)
            )
        },
    )
    logger.info(f"Коллекция создана: dense_dim={settings.embedding_dim}, sparse=BM25")


async def upsert_chunks_to_qdrant(
    client: AsyncQdrantClient,
    chunks: list[str],
    metadata_list: list[dict],
    batch_size: int = 10,
) -> int:
    """
    Загружает чанки в Qdrant батчами.

    Для каждого чанка создаёт:
    - Dense vector (qwen3-embedding)
    - Sparse vector (BM25)
    """
    total_uploaded = 0

    for i in range(0, len(chunks), batch_size):
        batch_texts = chunks[i : i + batch_size]
        batch_meta = metadata_list[i : i + batch_size]

        # Векторизация
        dense_vectors = await embed_texts_batch(batch_texts)
        sparse_vectors = compute_bm25_batch(batch_texts)

        points = []
        for text, meta, dense, sparse in zip(
            batch_texts, batch_meta, dense_vectors, sparse_vectors
        ):
            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "vectors": {
                        settings.qdrant_dense_vector_name: dense,
                        settings.qdrant_sparse_vector_name: {
                            "indices": list(sparse.indices),
                            "values": list(sparse.values),
                        },
                    },
                    "payload": {"text": text, **meta},
                }
            )

        await client.upsert(collection_name=settings.qdrant_collection, points=points)
        total_uploaded += len(points)

    return total_uploaded


# ── Основная логика ───────────────────────────────────────────────────────────

async def process_directory(
    qdrant: AsyncQdrantClient,
    directory: Path,
    source_type: str,
) -> int:
    """Обрабатывает все документы в директории и загружает в Qdrant."""
    if not directory.exists():
        logger.warning(f"Директория не найдена: {directory}")
        return 0

    supported = {".pdf", ".docx", ".doc", ".txt", ".eml"}
    files = [f for f in directory.rglob("*") if f.suffix.lower() in supported]

    if not files:
        logger.info(f"Файлы не найдены в: {directory}")
        return 0

    total = 0
    for filepath in tqdm(files, desc=f"[{source_type}]"):
        logger.info(f"  Обработка: {filepath.name}")

        # Извлечение текста
        try:
            suffix = filepath.suffix.lower()
            if suffix == ".pdf":
                text = extract_text_from_pdf(filepath)
            elif suffix in (".docx", ".doc"):
                text = extract_text_from_docx(filepath)
            elif suffix == ".eml":
                text = extract_text_from_eml(filepath)
            elif suffix == ".txt":
                async with aiofiles.open(filepath, encoding="utf-8", errors="replace") as f:
                    text = await f.read()
            else:
                continue
        except Exception as exc:
            logger.error(f"  Ошибка чтения {filepath.name}: {exc}")
            continue

        if not text.strip():
            logger.warning(f"  Пустой текст: {filepath.name}")
            continue

        # Разбивка на чанки
        chunks = split_into_chunks(text, settings.chunk_size, settings.chunk_overlap)
        logger.info(f"  Чанков: {len(chunks)}")

        # Метаданные для каждого чанка
        metadata_list = [
            {
                "source_file": filepath.name,
                "source_type": source_type,
                "file_path": str(filepath),
                "chunk_index": idx,
                "total_chunks": len(chunks),
            }
            for idx in range(len(chunks))
        ]

        # Загрузка в Qdrant
        uploaded = await upsert_chunks_to_qdrant(qdrant, chunks, metadata_list)
        total += uploaded
        logger.info(f"  ✓ Загружено чанков: {uploaded}")

    return total


async def main() -> None:
    logger.info("=== PDF/DOCX/EML Text Ingestion → Qdrant ===")

    qdrant = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    try:
        await ensure_qdrant_collection(qdrant)

        total = 0

        logger.info("→ Паспорта станков и инструкции (manuals/)...")
        total += await process_directory(qdrant, MANUALS_DIR, "manual")

        logger.info("→ ГОСТы и стандарты (gosts/)...")
        total += await process_directory(qdrant, GOSTS_DIR, "gost")

        logger.info("→ Деловая переписка (emails/)...")
        total += await process_directory(qdrant, EMAILS_DIR, "email")

        logger.info(f"=== Загрузка завершена. Итого чанков в Qdrant: {total} ===")
    finally:
        await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
