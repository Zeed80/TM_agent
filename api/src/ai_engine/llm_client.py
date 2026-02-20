"""
LLM Client — Qwen3:30b через Ollama GPU.

Используется для:
  - Text-to-Cypher (graph-search)
  - Text-to-SQL (inventory-sql)
  - Синтез финального ответа (docs-search)

Правило 1: timeout=120s (read/write).
Правило 2: num_ctx=16384 в каждом запросе.
"""

import logging
from typing import Any

import httpx

from src.config import settings
from src.ai_engine.vram_manager import VRAMManager

logger = logging.getLogger(__name__)

# Единый timeout для всех LLM-запросов (Правило 1)
_LLM_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=settings.llm_timeout,
    write=settings.llm_timeout,
    pool=5.0,
)


async def generate(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    top_p: float = 0.9,
    stop: list[str] | None = None,
) -> str:
    """
    Генерация текста через Qwen3:30b.

    Args:
        prompt: Пользовательский запрос или инструкция.
        system_prompt: Системный промпт (задаёт роль и ограничения).
        temperature: 0.0 для детерминированной генерации (Text-to-Cypher/SQL).
        top_p: Nucleus sampling.
        stop: Стоп-токены (например, ["```"] для обрезки кода).

    Returns:
        Сгенерированный текст (stripped).
    """
    vram = VRAMManager()
    await vram.ensure_llm()

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    request_body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": settings.llm_num_ctx,  # Правило 2: минимум 16384
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": 1.1,
        },
    }
    if stop:
        request_body["options"]["stop"] = stop

    logger.debug(
        f"[LLM] Запрос к {settings.llm_model}: "
        f"{len(messages)} сообщений, num_ctx={settings.llm_num_ctx}"
    )

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
        response = await client.post(
            f"{settings.ollama_gpu_url}/api/chat",
            json=request_body,
        )
        response.raise_for_status()
        data = response.json()

    content: str = data["message"]["content"].strip()
    logger.debug(f"[LLM] Ответ получен: {len(content)} символов")
    return content


async def generate_json(
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    """
    Генерация с принудительным JSON-форматом (Ollama format: json).
    Используется для Text-to-Cypher и Text-to-SQL где ответ должен быть JSON.

    Returns:
        JSON-строка (str). Парсинг — на стороне вызывающего кода с Pydantic.
    """
    vram = VRAMManager()
    await vram.ensure_llm()

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
        response = await client.post(
            f"{settings.ollama_gpu_url}/api/chat",
            json={
                "model": settings.llm_model,
                "messages": messages,
                "stream": False,
                "format": "json",  # Принуждаем Ollama вернуть валидный JSON
                "options": {
                    "num_ctx": settings.llm_num_ctx,  # Правило 2
                    "temperature": 0.0,  # Детерминированность критична для SQL/Cypher
                    "repeat_penalty": 1.1,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["message"]["content"].strip()
