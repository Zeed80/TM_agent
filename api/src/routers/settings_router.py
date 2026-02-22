"""
Настройки приложения: чтение/запись через Web UI.
Приоритет: значения из БД (заданные в админке) над .env.
"""
from fastapi import APIRouter, Depends, HTTPException

from src.app_settings import (
    get_all_for_ui,
    get_public_for_openclaw,
    set_setting,
    _SCHEMA,
)
from src.auth import get_current_admin

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", summary="Получить все настройки (админ)")
async def get_settings(
    _admin: dict = Depends(get_current_admin),
) -> dict:
    """
    Возвращает все настраиваемые параметры с текущими значениями
    (из БД или .env). Только для администратора.
    """
    return await get_all_for_ui()


@router.get("/public", summary="Публичные настройки для OpenClaw")
async def get_settings_public() -> dict:
    """
    Минимальный набор настроек без авторизации.
    Используется контейнером OpenClaw при старте (curl) для получения
    имени модели LLM и т.п.
    """
    return get_public_for_openclaw()


@router.patch("", summary="Обновить настройки (админ)")
async def patch_settings(
    body: dict,
    _admin: dict = Depends(get_current_admin),
) -> dict:
    """
    Обновить одну или несколько настроек. Тело: { "key": value, ... }.
    Неизвестные ключи игнорируются. Только для администратора.
    """
    updated = []
    for key, value in body.items():
        if key not in _SCHEMA:
            continue
        try:
            await set_setting(key, value)
            updated.append(key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"{key}: {e}") from e
    return {"updated": updated}
