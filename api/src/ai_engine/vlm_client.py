"""
VLM Client — Qwen3-VL:14b через Ollama GPU.

Используется для:
  - Анализа чертежей (blueprint-vision навык)
  - Извлечения технических требований: размеры, допуски, шероховатости, материал

Правило 1: timeout=120s (VLM медленнее LLM + время переключения модели).
Правило 2: num_ctx=16384.
VRAMManager.use_vlm() гарантирует эксклюзивный доступ к VRAM.
"""

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from src.app_settings import get_setting
from src.ai_engine.vram_manager import VRAMManager

logger = logging.getLogger(__name__)


def _vlm_timeout() -> httpx.Timeout:
    t = get_setting("vlm_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)


def _encode_image(image_path: str | Path) -> str:
    """Кодирует изображение в base64 для передачи в Ollama API."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def analyze_blueprint(
    image_path: str | Path,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """
    Анализирует чертёж через Qwen3-VL:14b.

    Захватывает VRAM через VRAMManager.use_vlm() — блокирует другие
    GPU-запросы на время анализа. После завершения LLM восстанавливается.

    Args:
        image_path: Путь к файлу чертежа (PNG, JPEG, PDF-превью).
        system_prompt: Системная инструкция для VLM.
        user_prompt: Конкретный вопрос или задание по чертежу.

    Returns:
        Текстовое описание технических требований чертежа.
    """
    vram = VRAMManager()

    image_b64 = _encode_image(image_path)
    logger.info(
        f"[VLM] Анализ чертежа: {image_path} "
        f"(размер изображения: {len(image_b64) // 1024}KB в base64)"
    )

    # Правило 1: use_vlm() применяет Lock и обеспечивает timeout 120s
    async with vram.use_vlm():
        async with httpx.AsyncClient(timeout=_vlm_timeout()) as client:
            response = await client.post(
                f"{get_setting('ollama_gpu_url')}/api/chat",
                json={
                    "model": get_setting("vlm_model"),
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                            "images": [image_b64],  # Ollama multimodal формат
                        },
                    ],
                    "stream": False,
                    "options": {
                        "num_ctx": get_setting("vlm_num_ctx"),  # Правило 2
                        "temperature": 0.0,  # Детерминированность для технических данных
                        "repeat_penalty": 1.1,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

    content: str = data["message"]["content"].strip()
    logger.info(f"[VLM] Анализ завершён: {len(content)} символов")
    return content


async def analyze_blueprint_from_bytes(
    image_bytes: bytes,
    image_format: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """
    Анализирует чертёж из байтов (например, из PDF-страницы).

    Args:
        image_bytes: Сырые байты изображения.
        image_format: Формат ('png', 'jpeg', 'jpg').
        system_prompt: Системная инструкция.
        user_prompt: Вопрос по чертежу.
    """
    vram = VRAMManager()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    logger.info(
        f"[VLM] Анализ чертежа из байтов "
        f"(формат: {image_format}, размер: {len(image_b64) // 1024}KB)"
    )

    async with vram.use_vlm():
        async with httpx.AsyncClient(timeout=_vlm_timeout()) as client:
            response = await client.post(
                f"{get_setting('ollama_gpu_url')}/api/chat",
                json={
                    "model": get_setting("vlm_model"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": user_prompt,
                            "images": [image_b64],
                        },
                    ],
                    "stream": False,
                    "options": {
                        "num_ctx": get_setting("vlm_num_ctx"),  # Правило 2
                        "temperature": 0.0,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

    return data["message"]["content"].strip()
