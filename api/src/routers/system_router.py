"""
Системный роутер — статус всех сервисов.

Endpoint: GET /api/v1/status
Возвращает состояние: Ollama GPU/CPU, Qdrant, Neo4j, PostgreSQL,
текущую модель в VRAM, использование дискового пространства документов.
"""

import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.ai_engine.vram_manager import VRAMManager
from src.auth import get_current_user
from src.app_settings import get_setting
from src.db.neo4j_client import neo4j_client
from src.db.postgres_client import postgres_client
from src.db.qdrant_client import qdrant_client

router = APIRouter(prefix="/api/v1/system", tags=["system"])
logger = logging.getLogger(__name__)


class ServiceStatus(BaseModel):
    name: str
    status: str          # "ok" | "error" | "unknown"
    detail: str | None = None
    latency_ms: float | None = None


class VRAMStatus(BaseModel):
    current_model: str | None
    gpu_available: bool


class DiskUsage(BaseModel):
    folder: str
    files_count: int
    total_size_mb: float


class FileWithStatus(BaseModel):
    id: str
    filename: str
    folder: str
    status: str  # 'uploaded' | 'processing' | 'indexed' | 'error'
    error_msg: str | None = None
    created_at: str
    indexed_at: str | None = None


class SystemStatusResponse(BaseModel):
    services: list[ServiceStatus]
    vram: VRAMStatus
    disk_usage: list[DiskUsage]
    llm_model: str
    vlm_model: str
    embedding_model: str
    reranker_model: str
    files_with_errors: list[FileWithStatus] | None = None


@router.get("/status", response_model=SystemStatusResponse)
async def system_status(
    current_user: dict = Depends(get_current_user),
) -> SystemStatusResponse:
    """
    Полный статус всех компонентов системы.
    Требует авторизации.
    """
    import time

    services: list[ServiceStatus] = []

    # ── PostgreSQL ───────────────────────────────────────────────────
    t = time.monotonic()
    try:
        ok = await postgres_client.health_check()
        services.append(ServiceStatus(
            name="PostgreSQL",
            status="ok" if ok else "error",
            latency_ms=round((time.monotonic() - t) * 1000, 1),
        ))
    except Exception as exc:
        services.append(ServiceStatus(name="PostgreSQL", status="error", detail=str(exc)))

    # ── Neo4j ────────────────────────────────────────────────────────
    t = time.monotonic()
    try:
        ok = await neo4j_client.health_check()
        services.append(ServiceStatus(
            name="Neo4j",
            status="ok" if ok else "error",
            latency_ms=round((time.monotonic() - t) * 1000, 1),
        ))
    except Exception as exc:
        services.append(ServiceStatus(name="Neo4j", status="error", detail=str(exc)))

    # ── Qdrant ───────────────────────────────────────────────────────
    t = time.monotonic()
    try:
        ok = await qdrant_client.health_check()
        services.append(ServiceStatus(
            name="Qdrant",
            status="ok" if ok else "error",
            latency_ms=round((time.monotonic() - t) * 1000, 1),
        ))
    except Exception as exc:
        services.append(ServiceStatus(name="Qdrant", status="error", detail=str(exc)))

    # ── Ollama GPU ───────────────────────────────────────────────────
    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{get_setting('ollama_gpu_url')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
        services.append(ServiceStatus(
            name="Ollama GPU",
            status="ok",
            detail=f"Загруженные модели: {', '.join(models) if models else 'нет'}",
            latency_ms=round((time.monotonic() - t) * 1000, 1),
        ))
    except Exception as exc:
        services.append(ServiceStatus(name="Ollama GPU", status="error", detail=str(exc)))

    # ── Ollama CPU ───────────────────────────────────────────────────
    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{get_setting('ollama_cpu_url')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
        services.append(ServiceStatus(
            name="Ollama CPU",
            status="ok",
            detail=f"Загруженные модели: {', '.join(models) if models else 'нет'}",
            latency_ms=round((time.monotonic() - t) * 1000, 1),
        ))
    except Exception as exc:
        services.append(ServiceStatus(name="Ollama CPU", status="error", detail=str(exc)))

    # ── VRAM Status ──────────────────────────────────────────────────
    vram = VRAMManager()
    gpu_available = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(f"{get_setting('ollama_gpu_url')}/api/ps")
            if resp.status_code == 200:
                gpu_available = True
    except Exception:
        pass

    vram_status = VRAMStatus(
        current_model=vram.current_model,
        gpu_available=gpu_available,
    )

    # ── Использование диска ──────────────────────────────────────────
    disk_usage: list[DiskUsage] = []
    base_dir = Path(get_setting("documents_base_dir"))
    for folder_name in ["blueprints", "invoices", "manuals", "gosts", "emails", "catalogs", "tech_processes"]:
        folder_path = base_dir / folder_name
        if folder_path.exists():
            files = list(folder_path.iterdir())
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            disk_usage.append(DiskUsage(
                folder=folder_name,
                files_count=len([f for f in files if f.is_file()]),
                total_size_mb=round(total_size / (1024 * 1024), 2),
            ))
        else:
            disk_usage.append(DiskUsage(folder=folder_name, files_count=0, total_size_mb=0.0))

    # ── Файлы с ошибками или в обработке ──────────────────────────
    files_with_errors: list[FileWithStatus] = []
    try:
        rows = await postgres_client.execute_query(
            """
            SELECT id, filename, folder, status, error_msg, created_at, indexed_at
            FROM uploaded_files
            WHERE status IN ('processing', 'error')
            ORDER BY created_at DESC
            LIMIT 20
            """,
            {},
        )
        for row in rows:
            files_with_errors.append(
                FileWithStatus(
                    id=str(row["id"]),
                    filename=row["filename"],
                    folder=row["folder"],
                    status=row["status"],
                    error_msg=row.get("error_msg"),
                    created_at=row["created_at"].isoformat() if row.get("created_at") else "",
                    indexed_at=row["indexed_at"].isoformat() if row.get("indexed_at") else None,
                )
            )
    except Exception as exc:
        logger.warning(f"[System] Не удалось получить файлы с ошибками: {exc}")

    return SystemStatusResponse(
        services=services,
        vram=vram_status,
        disk_usage=disk_usage,
        llm_model=get_setting("llm_model"),
        vlm_model=get_setting("vlm_model"),
        embedding_model=get_setting("embedding_model"),
        reranker_model=get_setting("reranker_model"),
        files_with_errors=files_with_errors,
    )
