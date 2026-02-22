"""
Настройки приложения с приоритетом БД над .env.
Все настраиваемые через Web UI параметры читаются через get_setting();
при отсутствии в БД используется значение из config (settings).
"""
import json
import logging
from typing import Any

from src.config import settings
from src.db.postgres_client import postgres_client

logger = logging.getLogger(__name__)

# Схема: ключ -> (тип для приведения, значение по умолчанию из settings)
# Значение по умолчанию берётся из settings при первом обращении к get_setting.
_SCHEMA: dict[str, tuple[str, Any]] = {
    # Ollama
    "ollama_gpu_url": ("str", None),
    "ollama_cpu_url": ("str", None),
    "ollama_models_path": ("str", None),
    # Модели (Ollama / default)
    "llm_model": ("str", None),
    "vlm_model": ("str", None),
    "embedding_model": ("str", None),
    "reranker_model": ("str", None),
    # Контекст и таймауты
    "llm_num_ctx": ("int", None),
    "vlm_num_ctx": ("int", None),
    "llm_timeout": ("float", None),
    "vlm_timeout": ("float", None),
    "embedding_timeout": ("float", None),
    "reranker_timeout": ("float", None),
    "vram_swap_timeout": ("float", None),
    # Qdrant
    "qdrant_collection": ("str", None),
    "embedding_dim": ("int", None),
    "qdrant_dense_vector_name": ("str", None),
    "qdrant_sparse_vector_name": ("str", None),
    "qdrant_prefetch_limit": ("int", None),
    "qdrant_final_limit": ("int", None),
    # Чат / агент
    "chat_max_tool_iterations": ("int", None),
    # Облака
    "cloud_llm_timeout": ("float", None),
    "cloud_embedding_timeout": ("float", None),
    "vllm_base_url": ("str_or_none", None),
    "openrouter_base_url": ("str", None),
    # Прочее
    "documents_base_dir": ("str", None),
    "cors_origins": ("str", None),
    # OpenClaw (модель по умолчанию для Telegram-агента; entrypoint может запросить через GET /settings/public)
    "openclaw_llm_model": ("str", None),
    "openclaw_auto_update": ("bool", None),
}

# Кэш: ключ -> значение (после загрузки из БД). None = не загружали.
_cache: dict[str, Any] | None = None

# Имена атрибутов в settings для fallback
_SETTINGS_ATTR: dict[str, str] = {
    "ollama_gpu_url": "ollama_gpu_url",
    "ollama_cpu_url": "ollama_cpu_url",
    "ollama_models_path": "ollama_models_path",
    "llm_model": "llm_model",
    "vlm_model": "vlm_model",
    "embedding_model": "embedding_model",
    "reranker_model": "reranker_model",
    "llm_num_ctx": "llm_num_ctx",
    "vlm_num_ctx": "vlm_num_ctx",
    "llm_timeout": "llm_timeout",
    "vlm_timeout": "vlm_timeout",
    "embedding_timeout": "embedding_timeout",
    "reranker_timeout": "reranker_timeout",
    "vram_swap_timeout": "vram_swap_timeout",
    "qdrant_collection": "qdrant_collection",
    "embedding_dim": "embedding_dim",
    "qdrant_dense_vector_name": "qdrant_dense_vector_name",
    "qdrant_sparse_vector_name": "qdrant_sparse_vector_name",
    "qdrant_prefetch_limit": "qdrant_prefetch_limit",
    "qdrant_final_limit": "qdrant_final_limit",
    "chat_max_tool_iterations": "chat_max_tool_iterations",
    "cloud_llm_timeout": "cloud_llm_timeout",
    "cloud_embedding_timeout": "cloud_embedding_timeout",
    "vllm_base_url": "vllm_base_url",
    "openrouter_base_url": "openrouter_base_url",
    "documents_base_dir": "documents_base_dir",
    "cors_origins": "cors_origins",
    "openclaw_llm_model": "llm_model",  # по умолчанию = llm_model
    "openclaw_auto_update": "openclaw_auto_update",
}


def _env_default(key: str) -> Any:
    """Значение из settings (.env) для ключа."""
    attr = _SETTINGS_ATTR.get(key, key)
    if not hasattr(settings, attr):
        if key == "openclaw_auto_update":
            return False
        return None
    return getattr(settings, attr)


def _coerce(typ: str, raw: Any) -> Any:
    if typ == "str":
        return str(raw) if raw is not None else ""
    if typ == "int":
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if typ == "float":
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    if typ == "bool":
        if raw is None:
            return False
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if typ == "str_or_none":
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        return str(raw).strip()
    return raw


async def load_from_db() -> None:
    """Загрузить настройки из БД в кэш. Вызывать при старте приложения."""
    global _cache
    _cache = {}
    try:
        rows = await postgres_client.execute_query(
            "SELECT key, value_json FROM app_settings",
            {},
        )
        for r in rows:
            k = (r.get("key") or "").strip()
            if k not in _SCHEMA:
                continue
            try:
                val = json.loads(r.get("value_json") or "null")
            except Exception:
                continue
            typ, _ = _SCHEMA[k]
            _cache[k] = _coerce(typ, val)
        logger.info("[app_settings] Загружено из БД: %s ключей", len(_cache))
    except Exception as e:
        logger.warning("[app_settings] Не удалось загрузить из БД: %s. Используем .env", e)
        _cache = {}


def get_setting(key: str) -> Any:
    """
    Текущее значение настройки: из кэша (БД) или из settings (.env).
    Синхронно; кэш должен быть заполнен при старте (load_from_db).
    """
    if key not in _SCHEMA:
        return _env_default(key)
    typ, _ = _SCHEMA[key]
    if _cache is not None and key in _cache:
        return _cache[key]
    return _coerce(typ, _env_default(key))


async def set_setting(key: str, value: Any) -> None:
    """Записать настройку в БД и обновить кэш."""
    if key not in _SCHEMA:
        raise ValueError(f"Unknown setting key: {key}")
    typ, _ = _SCHEMA[key]
    coerced = _coerce(typ, value)
    value_json = json.dumps(coerced) if coerced is not None else "null"
    await postgres_client.execute_query(
        """
        INSERT INTO app_settings (key, value_json)
        VALUES (:key, :value_json)
        ON CONFLICT (key) DO UPDATE SET value_json = EXCLUDED.value_json
        """,
        {"key": key, "value_json": value_json},
    )
    global _cache
    if _cache is not None:
        _cache[key] = coerced
    logger.info("[app_settings] Обновлено: %s", key)


async def get_all_for_ui() -> dict[str, Any]:
    """Все настройки с текущими значениями (для GET /settings)."""
    result = {}
    for key in _SCHEMA:
        result[key] = get_setting(key)
    return result


def get_public_for_openclaw() -> dict[str, Any]:
    """Минимальный набор для OpenClaw (GET /settings/public, без авторизации)."""
    return {
        "llm_model": get_setting("openclaw_llm_model") or get_setting("llm_model"),
    }
