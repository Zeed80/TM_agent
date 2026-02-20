"""
Blueprint Ingestion — Чертежи → VLM → Neo4j + Qdrant.

Поток для каждого чертежа:
  1. Читает изображение (PNG/JPEG/PDF→PNG)
  2. Отправляет в Qwen3-VL:14b → получает структурированные техтребования
  3. Парсит результат → извлекает номер чертежа, деталь, материал
  4. Создаёт узлы Drawing и Part в Neo4j (если не существуют)
  5. Добавляет текстовое описание в Qdrant (для docs-search)

Правило 1: timeout=120s на VLM (переключение GPU модели)
Правило 2: vlm_num_ctx=16384

Запуск: make ingest-blueprints
"""

import asyncio
import base64
import json
import logging
import re
import uuid
from pathlib import Path

import httpx
from fastembed import SparseTextEmbedding
from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient
from tqdm import tqdm

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BLUEPRINTS_DIR = Path(settings.documents_dir) / "blueprints"
_bm25_model = SparseTextEmbedding("Qdrant/bm25")

# Системный промпт для VLM (краткий вариант для ingestion)
_VLM_SYSTEM = """Ты — инженер-технолог. Анализируй машиностроительные чертежи по ЕСКД.
Отвечай только на русском языке. Будь точен в числах."""

# Промпт для структурированного извлечения (JSON для парсинга)
_VLM_EXTRACTION_PROMPT = """Проанализируй чертёж и извлеки данные в формате JSON:
{
  "drawing_number": "номер чертежа или пустая строка",
  "part_name": "наименование детали",
  "revision": "ревизия/литера или пустая строка",
  "material_grade": "марка материала (например: Сталь 45, PA6-GF30)",
  "material_gost": "ГОСТ материала или пустая строка",
  "tolerance_class": "квалитет точности (IT6, IT7...) или пустая строка",
  "roughness_ra": "Ra значение общей шероховатости (число) или null",
  "dimensions_summary": "краткое описание габаритов",
  "technical_requirements": "список ТТ через точку с запятой",
  "text_description": "полное текстовое описание для поиска (3-5 предложений)"
}
Верни ТОЛЬКО валидный JSON без markdown-обёртки."""


def _encode_image(filepath: Path) -> str:
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def analyze_blueprint_via_vlm(image_b64: str) -> dict:
    """
    Отправляет чертёж в Qwen3-VL и получает структурированный JSON.
    Правило 1: timeout=120s. Правило 2: num_ctx=16384.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.vlm_timeout, write=settings.vlm_timeout, pool=5.0)
    ) as client:
        response = await client.post(
            f"{settings.ollama_gpu_url}/api/chat",
            json={
                "model": settings.vlm_model,
                "messages": [
                    {"role": "system", "content": _VLM_SYSTEM},
                    {
                        "role": "user",
                        "content": _VLM_EXTRACTION_PROMPT,
                        "images": [image_b64],
                    },
                ],
                "stream": False,
                "format": "json",
                "options": {
                    "num_ctx": settings.vlm_num_ctx,  # Правило 2
                    "temperature": 0.0,
                },
            },
        )
        response.raise_for_status()
        raw = response.json()["message"]["content"].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Если модель вернула не чистый JSON — пробуем вытащить {}
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        logger.warning(f"VLM вернул невалидный JSON: {raw[:200]}")
        return {"part_name": "Неизвестно", "text_description": raw}


async def save_drawing_to_neo4j(
    driver,
    drawing_data: dict,
    file_path: str,
    qdrant_chunk_id: str,
) -> None:
    """Создаёт или обновляет узлы Drawing и Part в Neo4j."""
    drawing_number = drawing_data.get("drawing_number", "").strip() or f"UNKNOWN_{uuid.uuid4().hex[:8]}"
    part_name = drawing_data.get("part_name", "Неизвестная деталь").strip()
    revision = drawing_data.get("revision", "").strip()
    material_grade = drawing_data.get("material_grade", "").strip()
    tolerance_class = drawing_data.get("tolerance_class", "").strip()
    roughness_ra_raw = drawing_data.get("roughness_ra")

    try:
        roughness_ra = float(roughness_ra_raw) if roughness_ra_raw else None
    except (ValueError, TypeError):
        roughness_ra = None

    part_id = str(uuid.uuid4())
    drawing_id = str(uuid.uuid4())

    cypher = """
    MERGE (d:Drawing {drawing_number: $drawing_number, revision: $revision})
    ON CREATE SET
        d.id = $drawing_id,
        d.file_path = $file_path,
        d.qdrant_chunk_id = $qdrant_chunk_id
    ON MATCH SET
        d.file_path = $file_path,
        d.qdrant_chunk_id = $qdrant_chunk_id

    MERGE (p:Part {drawing_number: $drawing_number})
    ON CREATE SET
        p.id = $part_id,
        p.name = $part_name,
        p.tolerance_class = $tolerance_class,
        p.roughness_ra = $roughness_ra,
        p.created_at = datetime()
    ON MATCH SET
        p.name = $part_name

    MERGE (p)-[:HAS_DRAWING]->(d)

    WITH p, d
    WHERE $material_grade <> ''
    MERGE (m:Material {grade: $material_grade})
    ON CREATE SET
        m.id = $material_id,
        m.name = $material_grade,
        m.type = CASE
            WHEN $material_grade CONTAINS 'PA' OR $material_grade CONTAINS 'ABS'
                 OR $material_grade CONTAINS 'PP' OR $material_grade CONTAINS 'PE'
            THEN 'POLYMER'
            ELSE 'METAL'
        END
    MERGE (p)-[:MADE_FROM]->(m)
    """

    async with driver.session() as session:
        await session.run(
            cypher,
            {
                "drawing_number": drawing_number,
                "revision": revision,
                "drawing_id": drawing_id,
                "file_path": file_path,
                "qdrant_chunk_id": qdrant_chunk_id,
                "part_id": part_id,
                "part_name": part_name,
                "tolerance_class": tolerance_class,
                "roughness_ra": roughness_ra,
                "material_grade": material_grade,
                "material_id": str(uuid.uuid4()),
            },
        )


async def save_drawing_to_qdrant(
    qdrant: AsyncQdrantClient,
    text_description: str,
    drawing_data: dict,
    file_path: str,
) -> str:
    """Добавляет текстовое описание чертежа в Qdrant. Возвращает chunk_id."""
    chunk_id = str(uuid.uuid4())

    # Dense vector
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.embedding_timeout, write=settings.embedding_timeout, pool=5.0)
    ) as client:
        emb_response = await client.post(
            f"{settings.ollama_cpu_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": text_description},
        )
        emb_response.raise_for_status()
        dense_vector = emb_response.json()["embedding"]

    # Sparse BM25 vector (Правило 3)
    sparse_emb = list(_bm25_model.embed([text_description]))[0]
    sparse_vector = {"indices": list(sparse_emb.indices), "values": list(sparse_emb.values)}

    await qdrant.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            {
                "id": chunk_id,
                "vectors": {
                    settings.qdrant_dense_vector_name: dense_vector,
                    settings.qdrant_sparse_vector_name: sparse_vector,
                },
                "payload": {
                    "text": text_description,
                    "source_file": Path(file_path).name,
                    "source_type": "blueprint",
                    "drawing_number": drawing_data.get("drawing_number", ""),
                    "part_name": drawing_data.get("part_name", ""),
                    "material": drawing_data.get("material_grade", ""),
                },
            }
        ],
    )
    return chunk_id


async def main() -> None:
    logger.info("=== Blueprint Ingestion: Чертежи → VLM → Neo4j + Qdrant ===")

    if not BLUEPRINTS_DIR.exists():
        logger.error(f"Директория не найдена: {BLUEPRINTS_DIR}")
        return

    supported = {".png", ".jpg", ".jpeg", ".webp"}
    files = [f for f in BLUEPRINTS_DIR.rglob("*") if f.suffix.lower() in supported]

    if not files:
        logger.warning(f"Чертежи не найдены в {BLUEPRINTS_DIR}")
        return

    logger.info(f"Найдено чертежей: {len(files)}")

    neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    qdrant = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    success = 0
    errors = 0

    try:
        for filepath in tqdm(files, desc="Обработка чертежей"):
            logger.info(f"  → {filepath.name}")
            try:
                # Шаг 1: Кодируем изображение
                image_b64 = _encode_image(filepath)

                # Шаг 2: Анализ через VLM (Правило 1: timeout 120s)
                drawing_data = await analyze_blueprint_via_vlm(image_b64)
                logger.info(
                    f"    Деталь: {drawing_data.get('part_name', '?')}, "
                    f"Чертёж: {drawing_data.get('drawing_number', '?')}"
                )

                # Шаг 3: Сохранение в Qdrant (текстовое описание для поиска)
                text_description = drawing_data.get(
                    "text_description",
                    f"{drawing_data.get('part_name', '')} чертёж {drawing_data.get('drawing_number', '')}"
                )
                qdrant_chunk_id = await save_drawing_to_qdrant(
                    qdrant, text_description, drawing_data, str(filepath)
                )

                # Шаг 4: Сохранение в Neo4j (граф связей)
                await save_drawing_to_neo4j(
                    neo4j_driver, drawing_data, str(filepath), qdrant_chunk_id
                )

                success += 1
                logger.info(f"    ✓ Обработан: {filepath.name}")

            except Exception as exc:
                errors += 1
                logger.error(f"    ✗ Ошибка {filepath.name}: {exc}")

    finally:
        await neo4j_driver.close()
        await qdrant.close()

    logger.info(f"=== Blueprint Ingestion завершён. Успешно: {success}, Ошибок: {errors} ===")


if __name__ == "__main__":
    asyncio.run(main())
