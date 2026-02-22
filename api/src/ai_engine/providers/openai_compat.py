"""
OpenAI-совместимые провайдеры: OpenAI, OpenRouter, Anthropic, vLLM.

Реализация вызовов к API для LLM, VLM, Embedding, Reranker.
Ключи берутся из settings (env).
"""

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

_CLOUD_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=settings.cloud_llm_timeout,
    write=settings.cloud_llm_timeout,
    pool=5.0,
)
_EMBED_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=settings.cloud_embedding_timeout,
    write=settings.cloud_embedding_timeout,
    pool=5.0,
)


def _get_api_key(provider_type: str) -> str | None:
    key_by_type = {
        "openai": settings.openai_api_key,
        "openrouter": settings.openrouter_api_key,
        "anthropic": settings.anthropic_api_key,
    }
    key = key_by_type.get(provider_type)
    return (key and str(key).strip()) or None


def _get_base_url(provider_type: str, config: dict[str, Any]) -> str:
    url = (config.get("base_url") or "").strip()
    if url:
        return url.rstrip("/")
    if provider_type == "openrouter":
        return (settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    if provider_type == "openai":
        return "https://api.openai.com/v1"
    if provider_type == "vllm" and settings.vllm_base_url:
        return settings.vllm_base_url.rstrip("/")
    if provider_type == "anthropic":
        return "https://api.anthropic.com/v1"
    raise ValueError(f"Неизвестный провайдер или не задан base_url: {provider_type}")


def _build_messages(
    prompt: str,
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


async def llm_generate(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    top_p: float = 0.9,
    stop: list[str] | None = None,
) -> str:
    """Генерация текста через OpenAI-совместимый или Anthropic API."""
    api_key = _get_api_key(provider_type)
    if not api_key and provider_type != "vllm":
        raise RuntimeError(f"API-ключ для провайдера {provider_type} не задан. Укажите в настройках или env.")

    base_url = _get_base_url(provider_type, config)
    messages = _build_messages(prompt, system_prompt)

    if provider_type == "anthropic":
        return await _anthropic_chat(api_key, model_id, messages, temperature, top_p, stop)

    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
    }
    if top_p != 0.9:
        body["top_p"] = top_p
    if stop:
        body["stop"] = stop

    async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key or ''}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content", "").strip()


async def _anthropic_chat(
    api_key: str | None,
    model_id: str,
    messages: list[dict[str, Any]],
    temperature: float,
    top_p: float,
    stop: list[str] | None,
) -> str:
    if not api_key:
        raise RuntimeError("API-ключ Anthropic не задан.")
    system = ""
    user_messages = []
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
        else:
            user_messages.append(m)
    if not user_messages:
        return ""
    body: dict[str, Any] = {
        "model": model_id,
        "max_tokens": 8192,
        "system": system,
        "messages": user_messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if stop:
        body["stop_sequences"] = stop
    async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    for block in (data.get("content") or []):
        if block.get("type") == "text":
            return (block.get("text") or "").strip()
    return ""


async def llm_generate_json(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    """Генерация JSON (добавляем в системный промпт требование формата)."""
    sys = (system_prompt or "") + "\n\nОтветь только валидным JSON, без markdown и пояснений."
    return await llm_generate(
        provider_type=provider_type,
        model_id=model_id,
        config=config,
        assignment=assignment,
        prompt=prompt,
        system_prompt=sys.strip(),
        temperature=0.0,
    )


async def vlm_analyze(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    image_path: str | Path,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """VLM: анализ изображения (OpenAI vision или аналог)."""
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    ext = (Path(image_path).suffix or "").lower()
    fmt = "png" if ext == ".png" else "jpeg"
    return await vlm_analyze_from_bytes(
        provider_type=provider_type,
        model_id=model_id,
        config=config,
        assignment=assignment,
        image_bytes=image_bytes,
        image_format=fmt,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


async def vlm_analyze_from_bytes(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    image_bytes: bytes,
    image_format: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    api_key = _get_api_key(provider_type)
    if not api_key and provider_type != "vllm":
        raise RuntimeError(f"API-ключ для {provider_type} не задан.")
    base_url = _get_base_url(provider_type, config)
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime = "image/png" if image_format.lower() in ("png", "png") else "image/jpeg"
    content = [
        {"type": "text", "text": system_prompt + "\n\n" + user_prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ]
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key or ''}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content", "").strip()


async def embed_single(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    text: str,
) -> list[float]:
    """Embedding через OpenAI-совместимый API."""
    api_key = _get_api_key(provider_type)
    if not api_key and provider_type != "vllm":
        raise RuntimeError(f"API-ключ для {provider_type} не задан.")
    base_url = _get_base_url(provider_type, config)
    async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key or ''}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
    emb = (data.get("data") or [{}])[0]
    return emb.get("embedding", [])


async def embed_texts(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []
    api_key = _get_api_key(provider_type)
    if not api_key and provider_type != "vllm":
        raise RuntimeError(f"API-ключ для {provider_type} не задан.")
    base_url = _get_base_url(provider_type, config)
    async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key or ''}",
                "Content-Type": "application/json",
            },
            json={"model": model_id, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
    return [item.get("embedding", []) for item in (data.get("data") or [])]


async def rerank_batch(
    provider_type: str,
    model_id: str,
    config: dict[str, Any],
    assignment: dict[str, Any],
    query: str,
    documents: list[str],
) -> list[float]:
    """Reranker: облачные API часто не имеют cross-encoder; возвращаем нейтральные scores."""
    logger.warning(
        "[openai_compat] Reranker для облачного провайдера %s не реализован, возвращаем 0.5",
        provider_type,
    )
    return [0.5] * len(documents)
