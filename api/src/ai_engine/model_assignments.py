"""
Чтение назначений моделей по ролям из PostgreSQL с fallback на env.

Используется реестром провайдеров для выбора текущей модели по роли
(llm, vlm, embedding, reranker). При отсутствии записей в БД или ошибке
используются значения из settings (Ollama GPU/CPU по умолчанию).
"""

import logging
from typing import Any

from src.config import settings
from src.db.postgres_client import postgres_client

logger = logging.getLogger(__name__)

# Типы провайдеров, считающиеся облачными (данные уходят вовне)
CLOUD_PROVIDER_TYPES = frozenset({
    "openai", "anthropic", "openrouter", "google", "minimax", "z_ai",
})

# Роли моделей
ROLES = ("llm", "vlm", "embedding", "reranker")

# Дефолтные назначения из env (provider_type -> model_id для каждой роли)
_DEFAULT_OLLAMA_GPU_MODELS = {"llm": settings.llm_model, "vlm": settings.vlm_model}
_DEFAULT_OLLAMA_CPU_MODELS = {
    "embedding": settings.embedding_model,
    "reranker": settings.reranker_model,
}
# UUID провайдеров по умолчанию (из сидера 03_model_providers.sql)
_DEFAULT_OLLAMA_GPU_PROVIDER_ID = "a0000001-0000-4000-8000-000000000001"
_DEFAULT_OLLAMA_CPU_PROVIDER_ID = "a0000001-0000-4000-8000-000000000002"


def _is_cloud(provider_type: str) -> bool:
    return provider_type.lower() in CLOUD_PROVIDER_TYPES


async def get_all_assignments() -> dict[str, dict[str, Any]]:
    """
    Возвращает назначения по всем ролям из БД (с join на model_providers).
    При ошибке или пустой БД — fallback на значения из settings.

    Returns:
        dict[role, Assignment], где Assignment:
        - provider_id: str (UUID)
        - provider_type: str (ollama_gpu, openai, ...)
        - model_id: str
        - config: dict (url, base_url и т.д.)
        - is_cloud: bool
    """
    try:
        rows = await postgres_client.execute_query(
            """
            SELECT a.role, a.provider_id::text, a.model_id,
                   p.type AS provider_type, p.config
            FROM model_assignments a
            JOIN model_providers p ON p.id = a.provider_id
            WHERE a.role IN ('llm', 'vlm', 'embedding', 'reranker')
            """,
            {},
        )
    except Exception as exc:
        logger.warning(
            "[model_assignments] Не удалось загрузить назначения из БД: %s. Используем env.",
            exc,
        )
        return _fallback_assignments()

    if not rows:
        return _fallback_assignments()

    by_role = {r["role"]: r for r in rows}
    # Если не все роли заданы в БД — дополняем из fallback
    result: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        if role in by_role:
            r = by_role[role]
            config = r.get("config") or {}
            if isinstance(config, str):
                import json
                try:
                    config = json.loads(config) if config else {}
                except Exception:
                    config = {}
            provider_type = (r.get("provider_type") or "").strip().lower()
            result[role] = {
                "provider_id": str(r["provider_id"]),
                "provider_type": provider_type,
                "model_id": (r.get("model_id") or "").strip(),
                "config": config if isinstance(config, dict) else {},
                "is_cloud": _is_cloud(provider_type),
            }
        else:
            # берём из fallback для этой роли
            fallback = _fallback_assignments()
            result[role] = fallback[role]

    return result


def _fallback_assignments() -> dict[str, dict[str, Any]]:
    """Назначения из settings (Ollama GPU/CPU)."""
    return {
        "llm": {
            "provider_id": _DEFAULT_OLLAMA_GPU_PROVIDER_ID,
            "provider_type": "ollama_gpu",
            "model_id": settings.llm_model,
            "config": {"url": settings.ollama_gpu_url},
            "is_cloud": False,
        },
        "vlm": {
            "provider_id": _DEFAULT_OLLAMA_GPU_PROVIDER_ID,
            "provider_type": "ollama_gpu",
            "model_id": settings.vlm_model,
            "config": {"url": settings.ollama_gpu_url},
            "is_cloud": False,
        },
        "embedding": {
            "provider_id": _DEFAULT_OLLAMA_CPU_PROVIDER_ID,
            "provider_type": "ollama_cpu",
            "model_id": settings.embedding_model,
            "config": {"url": settings.ollama_cpu_url},
            "is_cloud": False,
        },
        "reranker": {
            "provider_id": _DEFAULT_OLLAMA_CPU_PROVIDER_ID,
            "provider_type": "ollama_cpu",
            "model_id": settings.reranker_model,
            "config": {"url": settings.ollama_cpu_url},
            "is_cloud": False,
        },
    }


async def get_assignment(role: str) -> dict[str, Any]:
    """
    Возвращает назначение для одной роли (llm, vlm, embedding, reranker).
    """
    all_assignments = await get_all_assignments()
    return all_assignments.get(role) or _fallback_assignments()[role]
