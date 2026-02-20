"""
Роутер навыка blueprint-vision.

Endpoint: POST /skills/blueprint-vision
Поток: путь к файлу → VLM (qwen3-vl:14b) → структурированный анализ чертежа

Правило 1: VRAMManager.use_vlm() обеспечивает Lock + timeout 120s.
Правило 2: vlm_num_ctx=16384 в vlm_client.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.ai_engine import vlm_client
from src.ai_engine.prompts.blueprint_analysis import (
    BLUEPRINT_FULL_EXTRACTION_PROMPT,
    BLUEPRINT_QUICK_ANALYSIS_PROMPT,
    BLUEPRINT_SYSTEM_PROMPT,
)
from src.models.sql_models import BlueprintVisionRequest, BlueprintVisionResponse

router = APIRouter(tags=["blueprint-vision"])
logger = logging.getLogger(__name__)

# Поддерживаемые форматы изображений
_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@router.post("/blueprint-vision", response_model=BlueprintVisionResponse)
async def blueprint_vision(request: BlueprintVisionRequest) -> BlueprintVisionResponse:
    """
    Навык blueprint-vision: анализ чертежа через Qwen3-VL:14b.

    Принимает путь к изображению, возвращает структурированные
    технические требования: размеры, допуски, материал, шероховатости.

    Вызывается OpenClaw через curl:
        curl -s -X POST http://api:8000/skills/blueprint-vision \\
          -H "Content-Type: application/json" \\
          -d '{"image_path": "/app/documents/blueprints/чертеж_123.png",
               "question": "Какой материал и основные допуски?"}'

    ВАЖНО: Путь должен начинаться с /app/documents/ (монтируется как volume).
    """
    logger.info(
        f"[blueprint-vision] Анализ чертежа: {request.image_path}, "
        f"вопрос: '{request.question[:80]}'"
    )

    # ── Проверка файла ────────────────────────────────────────────────
    image_path = Path(request.image_path)

    if not image_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Файл не найден: {request.image_path}. "
                "Убедись, что файл помещён в папку documents/ на сервере."
            ),
        )

    if image_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Неподдерживаемый формат: '{image_path.suffix}'. "
                f"Поддерживаются: {', '.join(_SUPPORTED_EXTENSIONS)}"
            ),
        )

    # ── Выбор промпта ─────────────────────────────────────────────────
    # Если вопрос стандартный (полный анализ) — используем подробный промпт
    is_full_analysis = request.question.lower().strip() in {
        "проанализируй чертёж и извлеки все технические требования",
        "проанализируй чертеж",
        "анализ чертежа",
        "full analysis",
    }

    if is_full_analysis:
        user_prompt = BLUEPRINT_FULL_EXTRACTION_PROMPT
    else:
        user_prompt = BLUEPRINT_QUICK_ANALYSIS_PROMPT.format(
            user_question=request.question
        )

    # ── Анализ через VLM ──────────────────────────────────────────────
    # vlm_client.analyze_blueprint использует VRAMManager.use_vlm()
    # который обеспечивает Lock (Правило 1) и timeout 120s
    try:
        analysis = await vlm_client.analyze_blueprint(
            image_path=image_path,
            system_prompt=BLUEPRINT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Файл чертежа не найден: {request.image_path}",
        )
    except Exception as exc:
        logger.error(f"[blueprint-vision] Ошибка VLM: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка анализа чертежа через VLM: {exc}",
        )

    logger.info(
        f"[blueprint-vision] Анализ завершён: {len(analysis)} символов"
    )

    return BlueprintVisionResponse(
        answer=analysis,
        image_path=request.image_path,
    )
