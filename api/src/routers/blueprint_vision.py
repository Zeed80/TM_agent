"""
Роутер навыка blueprint-vision.

Endpoint: POST /skills/blueprint-vision

АРХИТЕКТУРА (lookup-first):
  1. По image_path ищем Drawing в Neo4j (мгновенно, <50ms)
  2. Если найден → возвращаем предобработанные данные из графа + Qdrant
  3. Если НЕ найден → вызываем VLM (45-65 сек) → сохраняем результат в граф

Это значит:
  - 1-й запрос к новому чертежу: медленно (VLM + VRAM swap)
  - Все последующие: мгновенно (<200ms) без VLM

Правило 1: VRAMManager.use_vlm() обеспечивает Lock + timeout 120s.
Правило 2: vlm_num_ctx=16384 в vlm_client.
"""

import base64
import logging
import re
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from neo4j import AsyncGraphDatabase

from src.ai_engine import vlm_client
from src.ai_engine.prompts.blueprint_analysis import (
    BLUEPRINT_FULL_EXTRACTION_PROMPT,
    BLUEPRINT_QUICK_ANALYSIS_PROMPT,
    BLUEPRINT_SYSTEM_PROMPT,
)
from src.config import settings
from src.db import qdrant_client as _qdrant
from src.models.sql_models import BlueprintVisionRequest, BlueprintVisionResponse

router = APIRouter(tags=["blueprint-vision"])
logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


# ── Neo4j lookup ──────────────────────────────────────────────────────

async def _lookup_in_neo4j(file_path: str) -> dict | None:
    """
    Ищет чертёж в Neo4j по пути файла.
    Возвращает полные данные со всеми связями или None если не найден.
    """
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        async with driver.session() as session:
            result = await session.run("""
                MATCH (d:Drawing {file_path: $fp})-[:REPRESENTS]->(p:Part)
                OPTIONAL MATCH (p)-[:MADE_FROM]->(m:Material)
                OPTIONAL MATCH (p)-[op_rel:HAS_OPERATION]->(op:ManufacturingOperation)
                OPTIONAL MATCH (p)-[tool_rel:NEEDS_TOOL]->(t:ToolType)
                OPTIONAL MATCH (p)-[st_rel:REQUIRES_TREATMENT]->(st:SurfaceTreatment)
                OPTIONAL MATCH (p)-[ht_rel:HAS_HEAT_TREATMENT]->(ht:HeatTreatment)
                OPTIONAL MATCH (d)-[:HAS_QDRANT_CHUNK]->(q:QdrantRef)
                RETURN
                    d.drawing_number    AS drawing_number,
                    d.revision          AS revision,
                    d.scale             AS scale,
                    p.name              AS part_name,
                    p.tolerance_class   AS tolerance_class,
                    p.roughness_ra      AS roughness_ra,
                    p.dimensions_summary AS dimensions,
                    p.weight_kg         AS weight_kg,
                    p.technical_requirements AS tech_reqs,
                    m.grade             AS material_grade,
                    m.gost              AS material_gost,
                    m.type              AS material_type,
                    collect(DISTINCT {
                        sequence: op_rel.sequence,
                        name: op.name,
                        description: op.description,
                        machine_type: op.machine_type
                    }) AS operations,
                    collect(DISTINCT {
                        tool_type: t.name,
                        specification: tool_rel.specification,
                        purpose: tool_rel.purpose
                    }) AS tools,
                    st.type             AS surface_treatment,
                    st_rel.specification AS st_spec,
                    ht.type             AS heat_treatment,
                    ht_rel.hardness     AS ht_hardness,
                    q.chunk_id          AS qdrant_chunk_id
                LIMIT 1
            """, {"fp": file_path})

            record = await result.single()
            if not record:
                return None

            # Фильтруем пустые узлы из collect()
            ops = [
                op for op in (record.get("operations") or [])
                if op and op.get("name")
            ]
            ops_sorted = sorted(ops, key=lambda x: x.get("sequence") or 0)

            tools = [
                t for t in (record.get("tools") or [])
                if t and t.get("tool_type")
            ]

            return {
                "drawing_number":  record.get("drawing_number", ""),
                "revision":        record.get("revision", ""),
                "scale":           record.get("scale", ""),
                "part_name":       record.get("part_name", ""),
                "tolerance_class": record.get("tolerance_class", ""),
                "roughness_ra":    record.get("roughness_ra"),
                "dimensions":      record.get("dimensions", ""),
                "weight_kg":       record.get("weight_kg"),
                "tech_reqs":       record.get("tech_reqs", ""),
                "material_grade":  record.get("material_grade", ""),
                "material_gost":   record.get("material_gost", ""),
                "material_type":   record.get("material_type", ""),
                "operations":      ops_sorted,
                "tools":           tools,
                "surface_treatment": record.get("surface_treatment", ""),
                "st_spec":         record.get("st_spec", ""),
                "heat_treatment":  record.get("heat_treatment", ""),
                "ht_hardness":     record.get("ht_hardness", ""),
                "qdrant_chunk_id": record.get("qdrant_chunk_id", ""),
            }
    finally:
        await driver.close()


def _format_neo4j_answer(data: dict, question: str) -> str:
    """
    Форматирует данные из Neo4j в читаемый текстовый ответ.
    Фильтрует по теме вопроса если возможно.
    """
    q = question.lower()
    lines = []

    # Заголовок
    pn = data.get("part_name", "")
    dn = data.get("drawing_number", "")
    rev = data.get("revision", "")
    header = f"**{pn}**"
    if dn:
        header += f" (чертёж {dn}"
        if rev:
            header += f", ред. {rev}"
        header += ")"
    lines.append(header)
    lines.append("")

    # Материал
    mat = data.get("material_grade", "")
    if mat and any(k in q for k in ["материал", "марка", "из чего", "сталь", "полимер", "metal", ""]):
        mat_line = f"**Материал:** {mat}"
        if data.get("material_gost"):
            mat_line += f" ({data['material_gost']})"
        lines.append(mat_line)

    # Геометрия
    if data.get("dimensions") and any(k in q for k in ["размер", "габарит", "масс", "вес", ""]):
        lines.append(f"**Габариты:** {data['dimensions']}")
        if data.get("weight_kg"):
            lines.append(f"**Масса:** {data['weight_kg']} кг")

    # Точность и шероховатость
    if data.get("tolerance_class") or data.get("roughness_ra"):
        if any(k in q for k in ["точность", "квалитет", "шероховат", "допуск", ""]):
            tol_line = ""
            if data.get("tolerance_class"):
                tol_line += f"**Квалитет:** {data['tolerance_class']}  "
            if data.get("roughness_ra"):
                tol_line += f"**Ra:** {data['roughness_ra']} мкм"
            if tol_line:
                lines.append(tol_line.strip())

    # Операции (упорядоченные по sequence)
    ops = data.get("operations") or []
    if ops and any(k in q for k in ["операци", "технолог", "маршрут", "изготовл", "обработк", ""]):
        lines.append("")
        lines.append("**Маршрут изготовления:**")
        for op in ops:
            seq = op.get("sequence") or ""
            name = op.get("name", "")
            desc = op.get("description", "")
            mtype = op.get("machine_type", "")
            op_line = f"  {seq}. {name}"
            if desc:
                op_line += f" — {desc}"
            if mtype:
                op_line += f" [{mtype}]"
            lines.append(op_line)

    # Инструмент
    tools = data.get("tools") or []
    if tools and any(k in q for k in ["инструмент", "резец", "фреза", "сверло", "оснастк", ""]):
        lines.append("")
        lines.append("**Необходимый инструмент:**")
        for t in tools:
            t_line = f"  • {t.get('tool_type', '')}"
            if t.get("specification"):
                t_line += f" {t['specification']}"
            if t.get("purpose"):
                t_line += f" — {t['purpose']}"
            lines.append(t_line)

    # Термообработка / покрытие
    ht = data.get("heat_treatment", "")
    st = data.get("surface_treatment", "")
    if (ht or st) and any(k in q for k in ["термо", "закалк", "покрыт", "обработк", "твёрдост", ""]):
        if ht:
            ht_line = f"**Термообработка:** {ht}"
            if data.get("ht_hardness"):
                ht_line += f" ({data['ht_hardness']})"
            lines.append(ht_line)
        if st:
            st_line = f"**Покрытие:** {st}"
            if data.get("st_spec"):
                st_line += f" ({data['st_spec']})"
            lines.append(st_line)

    # Технические требования
    tech = data.get("tech_reqs", "")
    if tech and any(k in q for k in ["требован", "тт", "условия", ""]):
        lines.append("")
        lines.append(f"**Технические требования:** {tech}")

    # Источник
    lines.append("")
    lines.append("*Источник: производственная база знаний (предобработано при загрузке)*")

    return "\n".join(lines)


# ── Сохранение нового чертежа в граф после VLM ───────────────────────

async def _save_new_blueprint_to_graph(
    file_path: str,
    drawing_data: dict,
) -> None:
    """Сохраняет результат VLM-анализа нового чертежа в Neo4j и Qdrant."""
    from fastembed import SparseTextEmbedding
    import uuid as _uuid

    # Сохраняем в Qdrant
    text_description = drawing_data.get("text_description") or (
        f"{drawing_data.get('part_name', '')} чертёж {drawing_data.get('drawing_number', '')}"
    )

    # Sparse BM25
    _bm25 = SparseTextEmbedding("Qdrant/bm25")
    sparse_emb = list(_bm25.embed([text_description]))[0]
    sparse_vector = {"indices": list(sparse_emb.indices), "values": list(sparse_emb.values)}

    chunk_id = str(_uuid.uuid4())

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=settings.embedding_timeout, write=settings.embedding_timeout, pool=5.0)
    ) as client:
        emb_response = await client.post(
            f"{settings.ollama_cpu_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": text_description},
        )
        emb_response.raise_for_status()
        dense_vector = emb_response.json()["embedding"]

    ops = drawing_data.get("manufacturing_operations") or []
    tools = drawing_data.get("required_tools") or []

    await _qdrant.qdrant_client.client.upsert(
        collection_name=settings.qdrant_collection,
        points=[{
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
                "operations": [
                    op.get("name", "") for op in ops
                    if isinstance(op, dict) and op.get("name")
                ],
                "tools": [
                    t.get("tool_type", "") for t in tools
                    if isinstance(t, dict) and t.get("tool_type")
                ],
            },
        }],
    )

    # Сохраняем в Neo4j — переиспользуем логику из ingestion
    from ingestion.src.blueprint_ingestion import save_to_neo4j as _neo4j_save
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        await _neo4j_save(driver, drawing_data, file_path, chunk_id)
        logger.info(f"[blueprint-vision] Новый чертёж сохранён в граф: {Path(file_path).name}")
    finally:
        await driver.close()


# ── Endpoint ──────────────────────────────────────────────────────────

@router.post("/blueprint-vision", response_model=BlueprintVisionResponse)
async def blueprint_vision(request: BlueprintVisionRequest) -> BlueprintVisionResponse:
    """
    Навык blueprint-vision: анализ чертежа.

    Логика lookup-first:
      1. Ищет чертёж в Neo4j по file_path → если есть, отвечает мгновенно
      2. Если нет → запускает VLM (медленно) → сохраняет в граф для будущих запросов

    Принимает путь к изображению на сервере.
    """
    logger.info(
        f"[blueprint-vision] Запрос: {request.image_path}, "
        f"вопрос: '{request.question[:80]}'"
    )

    # ── Проверка файла ────────────────────────────────────────────────
    image_path = Path(request.image_path)

    if not image_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Файл не найден: {request.image_path}. "
                "Убедитесь, что файл помещён в папку documents/blueprints/ на сервере."
            ),
        )

    if image_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Неподдерживаемый формат '{image_path.suffix}'. "
                f"Поддерживаются: {', '.join(_SUPPORTED_EXTENSIONS)}"
            ),
        )

    # ── Шаг 1: Lookup в Neo4j (мгновенно) ────────────────────────────
    try:
        cached = await _lookup_in_neo4j(str(image_path))
    except Exception as exc:
        logger.warning(f"[blueprint-vision] Neo4j lookup ошибка: {exc}. Переходим к VLM.")
        cached = None

    if cached:
        logger.info(
            f"[blueprint-vision] ✓ Найдено в графе: "
            f"{cached.get('part_name')} / {cached.get('drawing_number')} "
            f"(операций: {len(cached.get('operations', []))}, "
            f"инструмента: {len(cached.get('tools', []))})"
        )
        answer = _format_neo4j_answer(cached, request.question)
        return BlueprintVisionResponse(
            answer=answer,
            image_path=request.image_path,
            source="graph_cache",
        )

    # ── Шаг 2: VLM (только для новых, ещё не проиндексированных чертежей) ──
    logger.info(
        f"[blueprint-vision] Чертёж не в базе → VLM анализ "
        f"(займёт 45-65 секунд, VRAM swap)..."
    )

    is_full_analysis = request.question.lower().strip() in {
        "проанализируй чертёж и извлеки все технические требования",
        "проанализируй чертеж",
        "анализ чертежа",
        "full analysis",
        "",
    }

    user_prompt = (
        BLUEPRINT_FULL_EXTRACTION_PROMPT if is_full_analysis
        else BLUEPRINT_QUICK_ANALYSIS_PROMPT.format(user_question=request.question)
    )

    try:
        analysis_text = await vlm_client.analyze_blueprint(
            image_path=image_path,
            system_prompt=BLUEPRINT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Файл не найден: {request.image_path}")
    except Exception as exc:
        logger.error(f"[blueprint-vision] Ошибка VLM: {exc}")
        raise HTTPException(status_code=503, detail=f"Ошибка VLM: {exc}")

    # ── Шаг 3: Сохраняем результат VLM в граф (асинхронно, не блокируем ответ) ──
    # Пытаемся распарсить JSON из VLM-ответа для сохранения в граф
    try:
        match = re.search(r"\{.*\}", analysis_text, re.DOTALL)
        if match:
            drawing_data = __import__("json").loads(match.group())
            drawing_data["text_description"] = analysis_text

            import asyncio
            asyncio.create_task(
                _save_new_blueprint_to_graph(str(image_path), drawing_data)
            )
            logger.info("[blueprint-vision] Запущено фоновое сохранение в граф")
    except Exception as save_exc:
        logger.warning(f"[blueprint-vision] Не удалось сохранить в граф: {save_exc}")

    logger.info(f"[blueprint-vision] VLM завершён: {len(analysis_text)} символов")

    return BlueprintVisionResponse(
        answer=analysis_text,
        image_path=request.image_path,
        source="vlm_fresh",
    )
