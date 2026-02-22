"""
Роутер реестра моделей: провайдеры, назначения по ролям, список локальных моделей Ollama.

Endpoints:
  GET  /api/v1/models/providers       — список провайдеров и их моделей (для UI)
  GET  /api/v1/models/assignments     — текущие назначения по ролям (llm, vlm, embedding, reranker)
  PUT  /api/v1/models/assignments     — обновить назначение (только admin)
  GET  /api/v1/models/local/ollama    — список моделей Ollama (GPU и CPU отдельно)
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app_settings import get_setting
from src.auth import get_current_admin, get_current_user
from src.config import settings
from src.db.postgres_client import postgres_client

router = APIRouter(prefix="/api/v1/models", tags=["models"])
logger = logging.getLogger(__name__)


# ─── Pydantic-модели ───────────────────────────────────────────────────

class ProviderInfo(BaseModel):
    id: str
    type: str
    name: str
    config: dict[str, Any]
    api_key_set: bool
    models: list[str] = []


class AssignmentItem(BaseModel):
    role: str
    provider_id: str
    provider_type: str
    model_id: str
    is_cloud: bool


class AssignmentsResponse(BaseModel):
    llm: AssignmentItem
    vlm: AssignmentItem
    embedding: AssignmentItem
    reranker: AssignmentItem


class PutAssignmentBody(BaseModel):
    role: str  # llm | vlm | embedding | reranker
    provider_id: str
    model_id: str


class PatchProviderBody(BaseModel):
    """Тело запроса для обновления провайдера (API-ключ задаётся только через админку)."""
    api_key: str | None = None  # задать ключ; пустая строка или null — удалить ключ


# ─── GET /providers ─────────────────────────────────────────────────────

@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(
    current_user: dict = Depends(get_current_user),
) -> list[ProviderInfo]:
    """
    Список провайдеров с метаданными и списком моделей.
    Для локальных (Ollama) модели запрашиваются у инстанса.
    """
    rows = await postgres_client.execute_query(
        "SELECT id::text, type, name, config, api_key_set FROM model_providers ORDER BY type",
        {},
    )
    result: list[ProviderInfo] = []
    for r in rows:
        config = r.get("config") or {}
        if isinstance(config, str):
            import json
            try:
                config = json.loads(config) if config else {}
            except Exception:
                config = {}
        models: list[str] = []
        ptype = (r.get("type") or "").strip().lower()
        # Ключ задаётся только в админке (БД), не в .env
        api_key_set = bool(r.get("api_key_set"))
        if ptype == "ollama_gpu":
            url = (config.get("url") or get_setting("ollama_gpu_url")).strip()
            models = await _ollama_list_models(url)
        elif ptype == "ollama_cpu":
            url = (config.get("url") or get_setting("ollama_cpu_url")).strip()
            models = await _ollama_list_models(url)
        elif ptype == "vllm":
            url = (get_setting("vllm_base_url") or "").strip().rstrip("/")
            models = await _vllm_list_models(url) if url else []
        else:
            # Облачные: ключ только из БД (админка), не из env
            models = _cloud_models_list(ptype, api_key_set)
        result.append(ProviderInfo(
            id=str(r["id"]),
            type=r["type"],
            name=r["name"],
            config=config if isinstance(config, dict) else {},
            api_key_set=api_key_set,
            models=models,
        ))
    return result


def _cloud_models_list(provider_type: str, api_key_set: bool) -> list[str]:
    """Список известных моделей для облачных провайдеров (статический или из кэша)."""
    if not api_key_set:
        return []
    openai_models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo",
        "o1", "o1-mini",
        "text-embedding-3-large", "text-embedding-3-small", "text-embedding-ada-002",
    ]
    anthropic_models = [
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307",
    ]
    openrouter_models = [
        "openai/gpt-4o", "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet", "anthropic/claude-3-opus",
        "google/gemini-pro", "meta-llama/llama-3.1-70b-instruct",
    ]
    by_type = {
        "openai": openai_models,
        "anthropic": anthropic_models,
        "openrouter": openrouter_models,
    }
    return by_type.get(provider_type, [])


async def _vllm_list_models(base_url: str) -> list[str]:
    """Список моделей vLLM (OpenAI-совместимый GET /v1/models)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{base_url}/v1/models")
            resp.raise_for_status()
            data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception as exc:
        logger.warning("[models] Не удалось получить список моделей vLLM %s: %s", base_url, exc)
        return []


async def _ollama_list_models(url: str) -> list[str]:
    """Запрос списка моделей у Ollama (GET /api/tags)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception as exc:
        logger.warning("[models] Не удалось получить список моделей Ollama %s: %s", url, exc)
        return []


# ─── GET /assignments ───────────────────────────────────────────────────

@router.get("/assignments", response_model=AssignmentsResponse)
async def get_assignments(
    current_user: dict = Depends(get_current_user),
) -> AssignmentsResponse:
    """Текущие назначения моделей по ролям (из БД или fallback на env)."""
    from src.ai_engine.model_assignments import get_all_assignments

    assignments = await get_all_assignments()
    def item(role: str) -> AssignmentItem:
        a = assignments.get(role) or {}
        return AssignmentItem(
            role=role,
            provider_id=a.get("provider_id", ""),
            provider_type=a.get("provider_type", ""),
            model_id=a.get("model_id", ""),
            is_cloud=a.get("is_cloud", False),
        )
    return AssignmentsResponse(
        llm=item("llm"),
        vlm=item("vlm"),
        embedding=item("embedding"),
        reranker=item("reranker"),
    )


# ─── PATCH /providers/:id (API-ключ только через админку) ───────────────

@router.patch("/providers/{provider_id}")
async def patch_provider(
    provider_id: str,
    body: PatchProviderBody,
    current_user: dict = Depends(get_current_admin),
) -> dict[str, str]:
    """
    Обновить настройки провайдера. API-ключ задаётся только здесь (не в .env).
    Передайте api_key для сохранения, null или пустую строку — чтобы удалить ключ.
    """
    from src.provider_keys import set_provider_api_key

    rows = await postgres_client.execute_query(
        "SELECT id FROM model_providers WHERE id = CAST(:pid AS uuid)",
        {"pid": provider_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Провайдер не найден")

    await set_provider_api_key(provider_id, body.api_key)
    return {"status": "ok", "message": "Ключ сохранён" if (body.api_key and body.api_key.strip()) else "Ключ удалён"}


# ─── PUT /assignments ───────────────────────────────────────────────────

@router.put("/assignments")
async def put_assignment(
    body: PutAssignmentBody,
    current_user: dict = Depends(get_current_admin),
) -> dict[str, str]:
    """Обновить назначение модели для роли (только admin)."""
    role = (body.role or "").strip().lower()
    if role not in ("llm", "vlm", "embedding", "reranker"):
        raise HTTPException(status_code=400, detail="Роль должна быть: llm, vlm, embedding или reranker")

    # Проверяем существование провайдера
    rows = await postgres_client.execute_query(
        "SELECT id FROM model_providers WHERE id = :pid",
        {"pid": body.provider_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Провайдер не найден")

    await postgres_client.execute_query(
        """
        INSERT INTO model_assignments (role, provider_id, model_id, updated_at)
        VALUES (:role, CAST(:pid AS uuid), :model_id, NOW())
        ON CONFLICT (role) DO UPDATE SET provider_id = CAST(:pid AS uuid), model_id = :model_id, updated_at = NOW()
        """,
        {"role": role, "pid": body.provider_id, "model_id": (body.model_id or "").strip()},
    )
    return {"status": "ok", "role": role, "model_id": body.model_id}


# ─── GET /local/ollama ─────────────────────────────────────────────────

class OllamaInstanceModels(BaseModel):
    instance: str  # gpu | cpu
    url: str
    models: list[str]


@router.get("/local/ollama", response_model=dict[str, OllamaInstanceModels])
async def list_local_ollama(
    current_user: dict = Depends(get_current_user),
) -> dict[str, OllamaInstanceModels]:
    """
    Список моделей по каждому инстансу Ollama (GPU и CPU).
    Для UI страницы «Локальные модели».
    """
    gpu_models = await _ollama_list_models(get_setting("ollama_gpu_url"))
    cpu_models = await _ollama_list_models(get_setting("ollama_cpu_url"))
    return {
        "gpu": OllamaInstanceModels(
            instance="gpu",
            url=get_setting("ollama_gpu_url"),
            models=gpu_models,
        ),
        "cpu": OllamaInstanceModels(
            instance="cpu",
            url=get_setting("ollama_cpu_url"),
            models=cpu_models,
        ),
    }
