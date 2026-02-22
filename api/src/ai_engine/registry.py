"""
Реестр провайдеров моделей: получение текущего назначения по роли
и вызов соответствующего провайдера (Ollama, OpenAI, OpenRouter и т.д.).
"""

import logging
from pathlib import Path
from typing import Any

from src.ai_engine.model_assignments import get_assignment
from src.ai_engine.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaLLMProvider,
    OllamaRerankerProvider,
    OllamaVLMProvider,
)

logger = logging.getLogger(__name__)


def _ollama_url(config: dict[str, Any]) -> str:
    from src.app_settings import get_setting
    url = (config.get("url") or "").strip()
    if not url:
        return get_setting("ollama_gpu_url")
    return url


# ─── LLM ───────────────────────────────────────────────────────────────

async def generate(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    top_p: float = 0.9,
    stop: list[str] | None = None,
) -> str:
    """Генерация текста через текущую LLM по назначению."""
    assignment = await get_assignment("llm")
    ptype = (assignment.get("provider_type") or "").strip().lower()
    model_id = (assignment.get("model_id") or "").strip()
    config = assignment.get("config") or {}

    if ptype == "ollama_gpu":
        url = _ollama_url(config)
        prov = OllamaLLMProvider(url=url, model_id=model_id)
        return await prov.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
        )
    if ptype in ("openai", "openrouter", "anthropic", "vllm"):
        # Облачные и vLLM — в следующих шагах
        from src.ai_engine.providers import openai_compat
        return await openai_compat.llm_generate(
            provider_type=ptype,
            model_id=model_id,
            config=config,
            assignment=assignment,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
        )

    # Fallback: Ollama GPU из настроек
    from src.app_settings import get_setting
    prov = OllamaLLMProvider(url=get_setting("ollama_gpu_url"), model_id=model_id or get_setting("llm_model"))
    return await prov.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        top_p=top_p,
        stop=stop,
    )


async def generate_json_llm(prompt: str, system_prompt: str | None = None) -> str:
    """Генерация JSON через текущую LLM."""
    assignment = await get_assignment("llm")
    ptype = (assignment.get("provider_type") or "").strip().lower()
    model_id = (assignment.get("model_id") or "").strip()
    config = assignment.get("config") or {}

    if ptype == "ollama_gpu":
        url = _ollama_url(config)
        prov = OllamaLLMProvider(url=url, model_id=model_id)
        return await prov.generate_json(prompt=prompt, system_prompt=system_prompt)
    if ptype in ("openai", "openrouter", "anthropic", "vllm"):
        from src.ai_engine.providers import openai_compat
        return await openai_compat.llm_generate_json(
            provider_type=ptype,
            model_id=model_id,
            config=config,
            assignment=assignment,
            prompt=prompt,
            system_prompt=system_prompt,
        )

    from src.app_settings import get_setting
    prov = OllamaLLMProvider(url=get_setting("ollama_gpu_url"), model_id=model_id or get_setting("llm_model"))
    return await prov.generate_json(prompt=prompt, system_prompt=system_prompt)


</think>
Удаляю ошибочный параметр `self` и добавляю заглушку для облачных провайдеров, чтобы реестр работал пока только с Ollama.
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
StrReplace