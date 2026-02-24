"""
Blueprint Ingestion — Чертежи → VLM → Neo4j + Qdrant.

Принцип: тяжёлая работа (VLM) выполняется ОДИН РАЗ при загрузке.
При последующих запросах через /skills/blueprint-vision данные
берутся из Neo4j/Qdrant — мгновенно, без VLM.

Что извлекает VLM за одно обращение:
  - Идентификация:  номер чертежа, наименование, ревизия
  - Материал:       марка, ГОСТ, тип (металл/полимер/композ.)
  - Геометрия:      габариты, масса, квалитет точности, шероховатость
  - Тех.требования: покрытие, термообработка, сварка, пайка и т.п.
  - Производство:   список операций (токарная, фрезерная, шлифование...)
  - Инструмент:     типы инструмента, необходимого для изготовления
  - Контроль:       КИО параметры, измерительный инструмент

Граф связей Neo4j (создаётся при ingestion):
  (:Drawing)-[:REPRESENTS]->(:Part)
  (:Part)-[:MADE_FROM]->(:Material)
  (:Part)-[:HAS_OPERATION {sequence}]->(:ManufacturingOperation)
  (:Part)-[:NEEDS_TOOL {purpose}]->(:ToolType)
  (:Part)-[:REQUIRES_TREATMENT]->(:SurfaceTreatment)
  (:Part)-[:HAS_HEAT_TREATMENT]->(:HeatTreatment)
  (:Drawing)-[:HAS_QDRANT_CHUNK {chunk_id}]->(:QdrantRef)

Запуск: make ingest-blueprints
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
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
INVOICES_DIR = Path(settings.documents_dir) / "invoices"
_bm25_model = SparseTextEmbedding("Qdrant/bm25")


# ── PostgreSQL функция ────────────────────────────────────────────────────

async def update_file_status(
    file_path: str,
    status: str = "indexed",
    error_msg: str | None = None,
):
    """Обновляет статус файла в таблице uploaded_files."""
    import asyncpg

    try:
        conn = await asyncpg.connect(settings.postgres_dsn)
        if status == "indexed":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = NULL, indexed_at = $2
                WHERE file_path = $3
                """,
                status,
                datetime.now(),
                file_path,
            )
        elif status == "processing":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = NULL
                WHERE file_path = $2
                """,
                status,
                file_path,
            )
        elif status == "error":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = $2, indexed_at = NULL
                WHERE file_path = $3
                """,
                status,
                error_msg,
                file_path,
            )
        await conn.close()
        logger.info(f"Обновлён статус файла {file_path}: {status}")
    except Exception as exc:
        logger.warning(f"Не удалось обновить статус файла {file_path}: {exc}")


# ── VLM промпты ───────────────────────────────────────────────────────

_VLM_SYSTEM = """Ты — опытный инженер-технолог. Анализируй машиностроительные чертежи по ЕСКД.
Отвечай ТОЛЬКО на русском языке. Будь максимально точен в числах, марках и обозначениях."""

_VLM_EXTRACTION_PROMPT = """Проанализируй машиностроительный чертёж и извлеки ВСЕ данные в формате JSON.

Верни СТРОГО JSON (без markdown, без пояснений):
{
  "drawing_number": "номер чертежа по основной надписи или ''",
  "part_name": "наименование детали (поле 1 основной надписи)",
  "revision": "ревизия/литера (А, Б, И, О...) или ''",
  "scale": "масштаб изображения (1:1, 1:2, 2:1...) или ''",

  "material_grade": "марка материала (Сталь 45, 12Х18Н10Т, PA6-GF30, АМц и т.п.)",
  "material_gost": "ГОСТ или ТУ на материал или ''",
  "material_type": "METAL | POLYMER | COMPOSITE | RUBBER | OTHER",

  "weight_kg": числовое значение массы в кг или null,
  "dimensions_summary": "краткие габариты (Ø50×120, 200×150×30 и т.п.)",
  "tolerance_class": "основной квалитет точности (IT6, IT7, H7/f6...) или ''",
  "roughness_ra": числовое значение Ra общей шероховатости или null,

  "technical_requirements": [
    "каждое ТТ отдельной строкой"
  ],

  "manufacturing_operations": [
    {
      "sequence": порядковый_номер,
      "name": "Токарная | Фрезерная | Сверлильная | Шлифовальная | Расточная | Нарезание резьбы | Зубонарезная | Долбёжная | Протяжная | Слесарная | Сборка | ТО | Контроль | ...",
      "description": "что конкретно делается",
      "machine_type": "тип станка если можно определить (токарный с ЧПУ, вертикально-фрезерный и т.п.) или ''",
      "note": "особенности или ''"
    }
  ],

  "required_tools": [
    {
      "tool_type": "тип инструмента (резец проходной, фреза торцевая, сверло, метчик, шлифовальный круг, измерительный инструмент...)",
      "specification": "конкретные параметры (Ø12, М20, T-MAX U CNMG 12...) или ''",
      "purpose": "для чего"
    }
  ],

  "surface_treatment": {
    "has_treatment": true | false,
    "type": "Хромирование | Никелирование | Анодирование | Оксидирование | Цинкование | Фосфатирование | Покраска | Закалка ТВЧ | Цементация | Нитрирование | '' ",
    "specification": "толщина, твёрдость, класс покрытия или ''"
  },

  "heat_treatment": {
    "has_treatment": true | false,
    "type": "Закалка | Отпуск | Отжиг | Нормализация | Цементация | Азотирование | ''",
    "hardness": "HRC 40-45 или HB 180-220 или ''",
    "specification": "дополнительные параметры или ''"
  },

  "welds": {
    "has_welds": true | false,
    "weld_types": ["тип сварки если есть"],
    "note": "особенности сборки"
  },

  "quality_control": {
    "measuring_tools": ["штангенциркуль", "микрометр", "нутромер", "калибр", "КИМ"],
    "critical_dimensions": "критичные размеры требующие особого контроля или ''"
  },

  "related_parts": [
    "обозначения сопряжённых деталей/сборок если видны на чертеже"
  ],

  "text_description": "Подробное описание (5-8 предложений) для семантического поиска. Включи: что за деталь, для чего, из чего сделана, основные операции изготовления, специфику обработки."
}"""

_VLM_INVOICE_SYSTEM = """Ты — помощник по учёту. Анализируй счета и платёжные документы.
Отвечай на русском. Извлекай ключевые данные для поиска."""

_VLM_INVOICE_PROMPT = """Опиши этот документ (счёт, накладная, акт) для поиска в базе.
Укажи: тип документа, номер и дату (если видны), контрагента/поставщика, суммы, перечень товаров/услуг (кратко).
Ответ дай одним связным текстом 3–8 предложений, без markdown."""


def _encode_image(filepath: Path) -> str:
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def analyze_blueprint_via_vlm(image_b64: str) -> dict:
    """Отправляет чертёж в Qwen3-VL и получает структурированный JSON."""
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
                    "num_ctx": settings.vlm_num_ctx,
                    "temperature": 0.0,
                },
            },
        )
        response.raise_for_status()
        raw = response.json()["message"]["content"].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"VLM вернул невалидный JSON: {raw[:300]}")
        return {"part_name": "Неизвестно", "text_description": raw, "material_grade": ""}


async def analyze_invoice_via_vlm(image_b64: str) -> str:
    """Отправляет изображение счёта в VLM и получает текстовое описание для поиска."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.vlm_timeout, write=settings.vlm_timeout, pool=5.0)
    ) as client:
        response = await client.post(
            f"{settings.ollama_gpu_url}/api/chat",
            json={
                "model": settings.vlm_model,
                "messages": [
                    {"role": "system", "content": _VLM_INVOICE_SYSTEM},
                    {
                        "role": "user",
                        "content": _VLM_INVOICE_PROMPT,
                        "images": [image_b64],
                    },
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        return (response.json().get("message", {}).get("content") or "").strip() or "Счёт (описание недоступно)"


async def save_invoice_to_qdrant(
    qdrant: AsyncQdrantClient,
    description: str,
    file_path: str,
) -> None:
    """Сохраняет описание счёта в Qdrant (только векторный поиск, без Neo4j)."""
    file_name = Path(file_path).name
    point_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.embedding_timeout, write=settings.embedding_timeout, pool=5.0)
    ) as client:
        emb_response = await client.post(
            f"{settings.ollama_cpu_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": description},
        )
        emb_response.raise_for_status()
        dense_vector = emb_response.json()["embedding"]

    sparse_emb = list(_bm25_model.embed([description]))[0]
    sparse_vector = {"indices": list(sparse_emb.indices), "values": list(sparse_emb.values)}

    await qdrant.upsert(
        collection_name=settings.qdrant_collection,
        points=[{
            "id": point_id,
            "vectors": {
                settings.qdrant_dense_vector_name: dense_vector,
                settings.qdrant_sparse_vector_name: sparse_vector,
            },
            "payload": {
                "text": description,
                "source_file": file_name,
                "source_type": "invoice",
                "file_path": file_path,
            },
        }],
    )


async def save_to_neo4j(
    driver,
    drawing_data: dict,
    file_path: str,
    qdrant_chunk_id: str,
) -> str:
    """
    Создаёт полный граф связей для чертежа в Neo4j.

    Узлы:
      Drawing, Part, Material, ManufacturingOperation,
      ToolType, SurfaceTreatment, HeatTreatment, QdrantRef

    Возвращает drawing_number для логирования.
    """
    drawing_number = (drawing_data.get("drawing_number") or "").strip()
    if not drawing_number:
        drawing_number = f"UNKNOWN_{uuid.uuid4().hex[:8]}"

    part_name      = (drawing_data.get("part_name") or "Неизвестная деталь").strip()
    revision       = (drawing_data.get("revision") or "").strip()
    material_grade = (drawing_data.get("material_grade") or "").strip()
    material_gost  = (drawing_data.get("material_gost") or "").strip()
    material_type  = (drawing_data.get("material_type") or "METAL").strip()
    dimensions     = (drawing_data.get("dimensions_summary") or "").strip()
    tolerance      = (drawing_data.get("tolerance_class") or "").strip()
    weight_kg      = drawing_data.get("weight_kg")
    scale          = (drawing_data.get("scale") or "").strip()
    tech_reqs      = drawing_data.get("technical_requirements") or []

    try:
        roughness_ra = float(drawing_data.get("roughness_ra") or 0) or None
    except (ValueError, TypeError):
        roughness_ra = None

    try:
        weight_val = float(weight_kg) if weight_kg else None
    except (ValueError, TypeError):
        weight_val = None

    # Обеспечиваем строковый формат tech_requirements
    if isinstance(tech_reqs, list):
        tech_reqs_str = "; ".join(str(r) for r in tech_reqs)
    else:
        tech_reqs_str = str(tech_reqs)

    async with driver.session() as session:

        # ── Шаг 1: Drawing + Part + Material ─────────────────────────
        await session.run("""
            MERGE (d:Drawing {drawing_number: $drawing_number, revision: $revision})
            ON CREATE SET
                d.id          = $drawing_id,
                d.file_path   = $file_path,
                d.scale       = $scale,
                d.indexed_at  = datetime()
            ON MATCH SET
                d.file_path   = $file_path,
                d.indexed_at  = datetime()

            MERGE (p:Part {drawing_number: $drawing_number})
            ON CREATE SET
                p.id                    = $part_id,
                p.name                  = $part_name,
                p.tolerance_class       = $tolerance_class,
                p.roughness_ra          = $roughness_ra,
                p.dimensions_summary    = $dimensions,
                p.weight_kg             = $weight_kg,
                p.technical_requirements = $tech_reqs,
                p.created_at            = datetime()
            ON MATCH SET
                p.name                  = $part_name,
                p.tolerance_class       = $tolerance_class,
                p.roughness_ra          = $roughness_ra,
                p.dimensions_summary    = $dimensions,
                p.weight_kg             = $weight_kg,
                p.technical_requirements = $tech_reqs

            MERGE (d)-[:REPRESENTS]->(p)
        """, {
            "drawing_number": drawing_number,
            "revision": revision,
            "drawing_id": str(uuid.uuid4()),
            "file_path": file_path,
            "scale": scale,
            "part_id": str(uuid.uuid4()),
            "part_name": part_name,
            "tolerance_class": tolerance,
            "roughness_ra": roughness_ra,
            "dimensions": dimensions,
            "weight_kg": weight_val,
            "tech_reqs": tech_reqs_str,
        })

        # ── Шаг 2: Material ──────────────────────────────────────────
        if material_grade:
            await session.run("""
                MATCH (p:Part {drawing_number: $drawing_number})
                MERGE (m:Material {grade: $grade})
                ON CREATE SET
                    m.id   = $mat_id,
                    m.name = $grade,
                    m.gost = $gost,
                    m.type = $mat_type
                ON MATCH SET
                    m.gost = $gost
                MERGE (p)-[:MADE_FROM]->(m)
            """, {
                "drawing_number": drawing_number,
                "grade": material_grade,
                "gost": material_gost,
                "mat_type": material_type,
                "mat_id": str(uuid.uuid4()),
            })

        # ── Шаг 3: Manufacturing Operations ──────────────────────────
        operations = drawing_data.get("manufacturing_operations") or []
        for op in operations:
            if not isinstance(op, dict):
                continue
            op_name = (op.get("name") or "").strip()
            if not op_name:
                continue
            await session.run("""
                MATCH (p:Part {drawing_number: $drawing_number})
                MERGE (o:ManufacturingOperation {
                    name: $op_name,
                    drawing_number: $drawing_number
                })
                ON CREATE SET
                    o.id           = $op_id,
                    o.description  = $description,
                    o.machine_type = $machine_type,
                    o.note         = $note
                ON MATCH SET
                    o.description  = $description,
                    o.machine_type = $machine_type
                MERGE (p)-[:HAS_OPERATION {sequence: $sequence}]->(o)
            """, {
                "drawing_number": drawing_number,
                "op_name": op_name,
                "op_id": str(uuid.uuid4()),
                "description": (op.get("description") or "").strip(),
                "machine_type": (op.get("machine_type") or "").strip(),
                "note": (op.get("note") or "").strip(),
                "sequence": int(op.get("sequence") or 0),
            })

        # ── Шаг 4: Required Tools ─────────────────────────────────────
        tools = drawing_data.get("required_tools") or []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_type = (tool.get("tool_type") or "").strip()
            if not tool_type:
                continue
            await session.run("""
                MATCH (p:Part {drawing_number: $drawing_number})
                MERGE (t:ToolType {name: $tool_type})
                ON CREATE SET
                    t.id = $tool_id
                MERGE (p)-[:NEEDS_TOOL {
                    specification: $spec,
                    purpose: $purpose
                }]->(t)
            """, {
                "drawing_number": drawing_number,
                "tool_type": tool_type,
                "tool_id": str(uuid.uuid4()),
                "spec": (tool.get("specification") or "").strip(),
                "purpose": (tool.get("purpose") or "").strip(),
            })

        # ── Шаг 5: Surface Treatment ──────────────────────────────────
        st = drawing_data.get("surface_treatment") or {}
        if isinstance(st, dict) and st.get("has_treatment") and st.get("type"):
            await session.run("""
                MATCH (p:Part {drawing_number: $drawing_number})
                MERGE (s:SurfaceTreatment {type: $stype})
                ON CREATE SET
                    s.id = $sid
                MERGE (p)-[:REQUIRES_TREATMENT {specification: $spec}]->(s)
            """, {
                "drawing_number": drawing_number,
                "stype": (st.get("type") or "").strip(),
                "sid": str(uuid.uuid4()),
                "spec": (st.get("specification") or "").strip(),
            })

        # ── Шаг 6: Heat Treatment ─────────────────────────────────────
        ht = drawing_data.get("heat_treatment") or {}
        if isinstance(ht, dict) and ht.get("has_treatment") and ht.get("type"):
            await session.run("""
                MATCH (p:Part {drawing_number: $drawing_number})
                MERGE (h:HeatTreatment {type: $htype})
                ON CREATE SET
                    h.id = $hid
                MERGE (p)-[:HAS_HEAT_TREATMENT {
                    hardness: $hardness,
                    specification: $spec
                }]->(h)
            """, {
                "drawing_number": drawing_number,
                "htype": (ht.get("type") or "").strip(),
                "hid": str(uuid.uuid4()),
                "hardness": (ht.get("hardness") or "").strip(),
                "spec": (ht.get("specification") or "").strip(),
            })

        # ── Шаг 7: Qdrant reference ───────────────────────────────────
        await session.run("""
            MATCH (d:Drawing {drawing_number: $drawing_number, revision: $revision})
            MERGE (q:QdrantRef {chunk_id: $chunk_id})
            ON CREATE SET
                q.collection = $collection
            MERGE (d)-[:HAS_QDRANT_CHUNK]->(q)
        """, {
            "drawing_number": drawing_number,
            "revision": revision,
            "chunk_id": qdrant_chunk_id,
            "collection": settings.qdrant_collection,
        })

    return drawing_number


async def save_to_qdrant(
    qdrant: AsyncQdrantClient,
    text_description: str,
    drawing_data: dict,
    file_path: str,
) -> str:
    """
    Сохраняет полное текстовое описание чертежа в Qdrant.
    Payload содержит все ключевые атрибуты для фильтрации.
    Возвращает chunk_id.
    """
    chunk_id = str(uuid.uuid4())
    file_name = Path(file_path).name

    # Строим обогащённый текст для лучшего поиска
    ops = drawing_data.get("manufacturing_operations") or []
    ops_text = ", ".join(
        op.get("name", "") for op in ops if isinstance(op, dict) and op.get("name")
    )
    tools = drawing_data.get("required_tools") or []
    tools_text = ", ".join(
        t.get("tool_type", "") for t in tools if isinstance(t, dict) and t.get("tool_type")
    )

    tech_reqs = drawing_data.get("technical_requirements") or []
    if isinstance(tech_reqs, list):
        tech_reqs_text = "; ".join(str(r) for r in tech_reqs)
    else:
        tech_reqs_text = str(tech_reqs)

    enriched_text = f"""{text_description}

Деталь: {drawing_data.get('part_name', '')}. Чертёж: {drawing_data.get('drawing_number', '')}.
Материал: {drawing_data.get('material_grade', '')} {drawing_data.get('material_gost', '')}.
Габариты: {drawing_data.get('dimensions_summary', '')}. Масса: {drawing_data.get('weight_kg', '') or ''} кг.
Точность: {drawing_data.get('tolerance_class', '')}. Шероховатость Ra {drawing_data.get('roughness_ra', '')}.
Операции изготовления: {ops_text}.
Необходимый инструмент: {tools_text}.
Технические требования: {tech_reqs_text}.
Файл: {file_name}."""

    # Dense vector
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.embedding_timeout, write=settings.embedding_timeout, pool=5.0)
    ) as client:
        emb_response = await client.post(
            f"{settings.ollama_cpu_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": enriched_text},
        )
        emb_response.raise_for_status()
        dense_vector = emb_response.json()["embedding"]

    # Sparse BM25 vector
    sparse_emb = list(_bm25_model.embed([enriched_text]))[0]
    sparse_vector = {"indices": list(sparse_emb.indices), "values": list(sparse_emb.values)}

    st = drawing_data.get("surface_treatment") or {}
    ht = drawing_data.get("heat_treatment") or {}

    await qdrant.upsert(
        collection_name=settings.qdrant_collection,
        points=[{
            "id": chunk_id,
            "vectors": {
                settings.qdrant_dense_vector_name: dense_vector,
                settings.qdrant_sparse_vector_name: sparse_vector,
            },
            "payload": {
                "text": enriched_text,
                "source_file": file_name,
                "source_type": "blueprint",
                "drawing_number": drawing_data.get("drawing_number", ""),
                "part_name": drawing_data.get("part_name", ""),
                "material": drawing_data.get("material_grade", ""),
                "material_type": drawing_data.get("material_type", ""),
                "operations": [
                    op.get("name", "") for op in ops
                    if isinstance(op, dict) and op.get("name")
                ],
                "tools": [
                    t.get("tool_type", "") for t in tools
                    if isinstance(t, dict) and t.get("tool_type")
                ],
                "surface_treatment": st.get("type", "") if isinstance(st, dict) else "",
                "heat_treatment": ht.get("type", "") if isinstance(ht, dict) else "",
                "tolerance_class": drawing_data.get("tolerance_class", ""),
                "weight_kg": drawing_data.get("weight_kg"),
                "dimensions": drawing_data.get("dimensions_summary", ""),
            },
        }],
    )
    return chunk_id


async def is_already_indexed(driver, file_path: str) -> bool:
    """Проверяет, был ли чертёж уже проиндексирован (по пути файла)."""
    async with driver.session() as session:
        result = await session.run(
            "MATCH (d:Drawing {file_path: $fp}) RETURN count(d) AS cnt",
            {"fp": file_path},
        )
        record = await result.single()
        return bool(record and record["cnt"] > 0)


async def main(force_reindex: bool = False) -> None:
    logger.info("=== Blueprint Ingestion: Чертежи + Счета → VLM → Neo4j + Qdrant ===")
    logger.info("Принцип: VLM вызывается ОДИН РАЗ при загрузке, затем поиск по графу.")

    supported = {".png", ".jpg", ".jpeg", ".webp"}
    files = []
    if BLUEPRINTS_DIR.exists():
        files = [f for f in BLUEPRINTS_DIR.rglob("*") if f.suffix.lower() in supported]
    if files:
        logger.info(f"Найдено чертежей: {len(files)}")

    neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    qdrant = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    success = errors = skipped = 0

    try:
        for filepath in tqdm(files, desc="Обработка чертежей"):
            file_path_str = str(filepath)

            # Пропускаем уже проиндексированные (если не force_reindex)
            if not force_reindex and await is_already_indexed(neo4j_driver, file_path_str):
                logger.info(f"  ⏭ Пропуск (уже проиндексирован): {filepath.name}")
                skipped += 1
                continue

            logger.info(f"  → VLM анализ: {filepath.name}")
            try:
                # Обновляем статус на processing
                await update_file_status(file_path_str, "processing")

                # Шаг 1: Кодируем изображение
                image_b64 = _encode_image(filepath)

                # Шаг 2: VLM — полное извлечение данных (выполняется ОДИН РАЗ)
                drawing_data = await analyze_blueprint_via_vlm(image_b64)
                logger.info(
                    f"    Деталь: {drawing_data.get('part_name', '?')} | "
                    f"Чертёж: {drawing_data.get('drawing_number', '?')} | "
                    f"Материал: {drawing_data.get('material_grade', '?')} | "
                    f"Операций: {len(drawing_data.get('manufacturing_operations') or [])}"
                )

                # Шаг 3: Qdrant — обогащённое текстовое описание
                text_description = drawing_data.get("text_description") or (
                    f"{drawing_data.get('part_name', '')} чертёж "
                    f"{drawing_data.get('drawing_number', '')}"
                )
                qdrant_chunk_id = await save_to_qdrant(
                    qdrant, text_description, drawing_data, file_path_str
                )

                # Шаг 4: Neo4j — полный граф связей
                drawing_number = await save_to_neo4j(
                    neo4j_driver, drawing_data, file_path_str, qdrant_chunk_id
                )

                # Обновляем статус на indexed
                await update_file_status(file_path_str, "indexed")

                success += 1
                ops_count = len(drawing_data.get("manufacturing_operations") or [])
                tools_count = len(drawing_data.get("required_tools") or [])
                logger.info(
                    f"    ✓ {filepath.name} → {drawing_number}: "
                    f"{ops_count} операций, {tools_count} типов инструмента"
                )

            except Exception as exc:
                errors += 1
                await update_file_status(file_path_str, "error", str(exc))
                logger.error(f"    ✗ Ошибка {filepath.name}: {exc}")

        # ── Счета (invoices): только изображения → VLM → Qdrant (без Neo4j) ──
        invoice_supported = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif"}
        invoice_files = []
        if INVOICES_DIR.exists():
            invoice_files = [f for f in INVOICES_DIR.rglob("*") if f.suffix.lower() in invoice_supported]

        for filepath in tqdm(invoice_files, desc="Обработка счетов"):
            file_path_str = str(filepath)
            try:
                # Обновляем статус на processing
                await update_file_status(file_path_str, "processing")

                image_b64 = _encode_image(filepath)
                description = await analyze_invoice_via_vlm(image_b64)
                await save_invoice_to_qdrant(qdrant, description, file_path_str)

                # Обновляем статус на indexed
                await update_file_status(file_path_str, "indexed")

                success += 1
                logger.info(f"  ✓ Счёт: {filepath.name}")
            except Exception as exc:
                errors += 1
                await update_file_status(file_path_str, "error", str(exc))
                logger.error(f"  ✗ Ошибка счёта {filepath.name}: {exc}")

    finally:
        await neo4j_driver.close()
        await qdrant.close()

    logger.info(
        f"=== Blueprint Ingestion завершён. "
        f"Обработано: {success}, Пропущено: {skipped}, Ошибок: {errors} ==="
    )
    if success > 0:
        logger.info(
            "Теперь запросы /skills/blueprint-vision будут отвечать из Neo4j/Qdrant "
            "мгновенно — без VLM и без VRAM swap."
        )


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    asyncio.run(main(force_reindex=force))
