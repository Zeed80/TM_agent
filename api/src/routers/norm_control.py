"""
Роутер навыка norm-control (нормоконтроль).

Endpoint: POST /skills/norm-control
Поток: document_type + identifier (или image_path) → данные документа из графа/VLM →
       поиск ГОСТов в Qdrant → LLM (отчёт в JSON) → ответ passed/checks/summary.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.ai_engine import registry
from src.ai_engine.prompts.blueprint_analysis import (
    BLUEPRINT_FULL_EXTRACTION_PROMPT,
    BLUEPRINT_SYSTEM_PROMPT,
)
from src.ai_engine.prompts.norm_control import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from src.db.neo4j_client import neo4j_client
from src.db.qdrant_client import qdrant_client
from src.models.sql_models import (
    NormControlCheckItem,
    NormControlRequest,
    NormControlResponse,
)

router = APIRouter(tags=["norm-control"])
logger = logging.getLogger(__name__)

# Запрос для поиска релевантных ГОСТов и норм в Qdrant
GOST_SEARCH_QUERIES = [
    "ГОСТ ЕСКД оформление чертежей основная надпись обозначения",
    "нормоконтроль техпроцессов оформление операций требования",
]


async def _get_drawing_data_from_graph(identifier: str) -> str:
    """Получить данные чертежа из Neo4j по номеру чертежа."""
    cypher = """
    MATCH (d:Drawing)-[:REPRESENTS]->(p:Part)
    WHERE d.drawing_number = $identifier
    OPTIONAL MATCH (p)-[:MADE_FROM]->(m:Material)
    RETURN d.drawing_number AS drawing_number, d.revision AS revision,
           p.name AS part_name, p.tolerance_class, p.roughness_ra,
           p.dimensions_summary, p.weight_kg, p.technical_requirements,
           m.grade AS material_grade, m.gost AS material_gost
    LIMIT 1
    """
    records = await neo4j_client.run_query(cypher, {"identifier": identifier})
    if not records:
        return f"Чертёж с номером '{identifier}' в графе не найден."
    return json.dumps(records[0], ensure_ascii=False, indent=2)


async def _get_tech_process_data_from_graph(identifier: str) -> str:
    """Получить данные техпроцесса из Neo4j по номеру."""
    cypher = """
    MATCH (tp:TechProcess)-[:FOR_PART]->(p:Part)
    WHERE tp.number = $identifier
    OPTIONAL MATCH (tp)-[r:HAS_OPERATION]->(op:Operation)
    OPTIONAL MATCH (op)-[:PERFORMED_ON]->(m:Machine)
    RETURN tp.number AS techprocess_number, tp.revision, tp.status,
           p.name AS part_name, p.drawing_number,
           r.sequence AS sequence, op.name AS op_name, op.number AS op_number,
           op.description, op.setup_time_min, op.machine_time_min,
           m.name AS machine_name
    ORDER BY r.sequence
    LIMIT 100
    """
    records = await neo4j_client.run_query(cypher, {"identifier": identifier})
    if not records or records[0].get("techprocess_number") is None:
        return f"Техпроцесс с номером '{identifier}' в графе не найден."
    # Собираем уникальные данные техпроцесса и список операций
    first = records[0]
    out = {
        "techprocess_number": first.get("techprocess_number"),
        "revision": first.get("revision"),
        "status": first.get("status"),
        "part_name": first.get("part_name"),
        "drawing_number": first.get("drawing_number"),
        "operations": [
            {
                "sequence": r.get("sequence"),
                "op_name": r.get("op_name"),
                "op_number": r.get("op_number"),
                "description": r.get("description"),
                "setup_time_min": r.get("setup_time_min"),
                "machine_time_min": r.get("machine_time_min"),
                "machine_name": r.get("machine_name"),
            }
            for r in records if r.get("op_name") is not None
        ],
    }
    return json.dumps(out, ensure_ascii=False, indent=2)


async def _get_gost_excerpts() -> str:
    """Получить выдержки из ГОСТов/норм через hybrid search в Qdrant."""
    dense_vectors = []
    all_candidates = []

    for query in GOST_SEARCH_QUERIES:
        try:
            dense_vec = await registry.embed_single(query)
        except Exception as exc:
            logger.warning(f"[norm-control] Ошибка embedding для '{query[:50]}': {exc}")
            continue

        try:
            candidates = await qdrant_client.hybrid_search(
                query_text=query,
                dense_vector=dense_vec,
                top_k=5,
            )
            all_candidates.extend(candidates)
        except Exception as exc:
            logger.warning(f"[norm-control] Ошибка Qdrant для '{query[:50]}': {exc}")

    if not all_candidates:
        return (
            "В базе документации завода не найдено выдержек по ГОСТам и нормам оформления. "
            "Загрузите документы в папку documents/gosts/ и выполните индексацию (make ingest-pdf или через Админку)."
        )

    # Убираем дубликаты по тексту, берём до 10 уникальных фрагментов
    seen_texts: set[str] = set()
    parts = []
    for point in all_candidates[:20]:
        payload = point.payload or {}
        text = (payload.get("text") or "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        source = payload.get("source_file", payload.get("source", "Документ"))
        parts.append(f"[Источник: {source}]\n{text[:1500]}")
        if len(parts) >= 10:
            break

    return "\n\n---\n\n".join(parts) if parts else "Релевантные фрагменты не найдены."


def _parse_report_json(raw: str) -> NormControlResponse:
    """Извлечь JSON из ответа LLM и собрать NormControlResponse."""
    raw = raw.strip()
    # Убрать markdown-обёртку если есть
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[norm-control] Невалидный JSON от LLM: {e}. Raw: {raw[:300]}")
        return NormControlResponse(
            passed=False,
            checks=[],
            summary="Не удалось сформировать структурированный отчёт. Проверьте наличие данных документа и ГОСТов в системе.",
        )

    passed = bool(data.get("passed", False))
    checks_raw = data.get("checks") or []
    checks = []
    for c in checks_raw:
        if isinstance(c, dict):
            checks.append(
                NormControlCheckItem(
                    name=str(c.get("name", "")),
                    status=str(c.get("status", "failed")).lower()[:10],
                    comment=str(c.get("comment", "")),
                )
            )
    summary = str(data.get("summary", "")).strip() or ("Нормоконтроль пройден." if passed else "Нормоконтроль не пройден.")
    return NormControlResponse(passed=passed, checks=checks, summary=summary)


@router.post("/norm-control", response_model=NormControlResponse)
async def norm_control(request: NormControlRequest) -> NormControlResponse:
    """
    Навык norm-control: проверка чертежа или техпроцесса на соответствие нормам и ГОСТам.

    - document_type: "drawing" | "tech_process"
    - identifier: номер чертежа или номер техпроцесса (обязателен для поиска в графе)
    - image_path: путь к файлу чертежа (опционально; при указании для drawing выполняется VLM-анализ)
    """
    doc_type = (request.document_type or "").strip().lower()
    identifier = (request.identifier or "").strip()
    image_path = request.image_path and request.image_path.strip() or None

    if doc_type not in ("drawing", "tech_process"):
        raise HTTPException(
            status_code=400,
            detail="document_type должен быть 'drawing' или 'tech_process'",
        )

    if doc_type == "tech_process" and not identifier:
        raise HTTPException(
            status_code=400,
            detail="Для техпроцесса укажите identifier (номер техпроцесса).",
        )

    if doc_type == "drawing" and not identifier and not image_path:
        raise HTTPException(
            status_code=400,
            detail="Для чертежа укажите identifier (номер чертежа) или image_path.",
        )

    logger.info(f"[norm-control] Запрос: type={doc_type}, identifier={identifier!r}, image_path={image_path!r}")

    # ── Шаг 1: Данные документа ───────────────────────────────────────
    if doc_type == "drawing":
        if image_path:
            path = Path(image_path)
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Файл не найден: {image_path}")
            try:
                analysis_text = await registry.analyze_blueprint(
                    image_path=path,
                    system_prompt=BLUEPRINT_SYSTEM_PROMPT,
                    user_prompt=BLUEPRINT_FULL_EXTRACTION_PROMPT,
                )
                document_data = analysis_text
            except Exception as exc:
                logger.error(f"[norm-control] Ошибка VLM для чертежа: {exc}")
                raise HTTPException(status_code=503, detail=f"Ошибка анализа чертежа: {exc}")
        else:
            document_data = await _get_drawing_data_from_graph(identifier)
    else:
        document_data = await _get_tech_process_data_from_graph(identifier)

    # ── Шаг 2: Выдержки из ГОСТов ────────────────────────────────────
    gost_excerpts = await _get_gost_excerpts()

    # ── Шаг 3: Генерация отчёта через LLM ─────────────────────────────
    user_prompt = USER_PROMPT_TEMPLATE.format(
        document_data=document_data,
        gost_excerpts=gost_excerpts,
    )

    try:
        raw_json = await registry.generate_json_llm(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.error(f"[norm-control] Ошибка LLM: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка формирования отчёта нормоконтроля: {exc}",
        )

    response = _parse_report_json(raw_json)
    logger.info(f"[norm-control] Результат: passed={response.passed}, checks={len(response.checks)}")
    return response
