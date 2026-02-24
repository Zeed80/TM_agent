"""
Роутер управления индексацией документов.

Запускает ingestion-скрипты через docker exec и стримит прогресс через SSE.

Endpoints:
  POST /api/v1/indexing/start/{task}     — запуск индексации
  GET  /api/v1/indexing/status             — SSE поток статуса файлов
  GET  /api/v1/indexing/files              — список файлов со статусами
  POST /api/v1/indexing/reindex/{file_id}  — переиндексация файла
"""

import asyncio
import json
import logging
import queue as sync_queue
import threading
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.app_settings import get_setting
from src.auth import get_current_admin

router = APIRouter(prefix="/api/v1/indexing", tags=["indexing"])
logger = logging.getLogger(__name__)

# Docker-клиент (синглтон)
_docker_client = None


def _get_docker():
    """Получить Docker-клиент."""
    global _docker_client
    if _docker_client is None:
        try:
            import docker as docker_sdk
            _docker_client = docker_sdk.DockerClient(base_url="unix:///var/run/docker.sock")
            _docker_client.ping()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Docker-сокет недоступен: {exc}",
            )
    return _docker_client


class IndexingTask(str):
    """Допустимые задачи индексации."""
    BLUEPRINTS = "blueprints"
    INVOICES = "invoices"
    MANUALS = "manuals"
    GOSTS = "gosts"
    EMAILS = "emails"
    CATALOGS = "catalogs"
    TECH_PROCESSES = "tech_processes"
    ALL = "all"


TASK_DESCRIPTIONS = {
    IndexingTask.BLUEPRINTS: "Чертежи → VLM → Neo4j + Qdrant",
    IndexingTask.INVOICES: "Счета → VLM → Qdrant",
    IndexingTask.MANUALS: "Паспорта станков → Qdrant",
    IndexingTask.GOSTS: "ГОСТы и стандарты → Qdrant",
    IndexingTask.EMAILS: "Переписка → Qdrant",
    IndexingTask.CATALOGS: "Каталоги → PostgreSQL",
    IndexingTask.TECH_PROCESSES: "Техпроцессы → Neo4j",
    IndexingTask.ALL: "Все документы",
}

INGESTION_SCRIPTS = {
    IndexingTask.BLUEPRINTS: "src.blueprint_ingestion",
    IndexingTask.MANUALS: "src.pdf_text_ingestion",
    IndexingTask.GOSTS: "src.pdf_text_ingestion",
    IndexingTask.EMAILS: "src.pdf_text_ingestion",
    IndexingTask.CATALOGS: "src.excel_ingestion",
    IndexingTask.TECH_PROCESSES: "src.tech_process_ingestion",
}


@router.post("/start/{task}")
async def start_indexing(
    task: str,
    _admin: dict = Depends(get_current_admin),
) -> StreamingResponse:
    """
    Запускает индексацию через docker exec в контейнере ingestion.
    Результат стримится как SSE.
    """
    if task not in IndexingTask.__members__.values() and task != "all":
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная задача '{task}'. Доступные: {', '.join(TASK_DESCRIPTIONS.keys())}",
        )

    return StreamingResponse(
        _run_ingestion_stream(task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_ingestion_stream(task: str) -> AsyncGenerator[str, None]:
    """Запускает ingestion в docker контейнере и стримит вывод."""
    yield f"data: {json.dumps({'type': 'start', 'task': task, 'description': TASK_DESCRIPTIONS.get(task, task)})}\n\n"

    scripts = []
    if task == "all":
        scripts = list(INGESTION_SCRIPTS.values())
    elif task in INGESTION_SCRIPTS:
        scripts = [INGESTION_SCRIPTS[task]]

    def _run_scripts():
        client = _get_docker()
        results = []
        try:
            container = client.containers.get("ingestion")
        except Exception:
            results.append(("[ERROR]", "Контейнер 'ingestion' не запущен. Запустите: docker compose --profile ingestion up ingestion"))
            return results

        for script in scripts:
            exit_code, output = container.exec_run(
                f"python -m {script}",
                stream=False,
                demux=False,
            )
            results.append((str(exit_code), output.decode("utf-8", errors="replace") if output else ""))
        return results

    try:
        results = await asyncio.to_thread(_run_scripts)
        for exit_code, output in results:
            for line in output.split("\n"):
                if line.strip():
                    yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@router.get("/status")
async def get_indexing_status_sse(
    _user: dict = Depends(get_current_admin),
) -> StreamingResponse:
    """
    SSE поток статуса индексации файлов.
    Стримит информацию о файлах с их статусами.
    """
    from src.db.postgres_client import postgres_client as _pg

    async def _status_generator():
        """Генератор SSE событий для статуса файлов."""
        try:
            while True:
                await asyncio.sleep(2)  # Обновление каждые 2 секунды

                # Получаем статус файлов
                rows = await _pg.execute_query(
                    """
                    SELECT id, filename, folder, status, error_msg, created_at, indexed_at
                    FROM uploaded_files
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    {},
                )

                # Группируем по статусам
                status_summary = {
                    "uploaded": 0,
                    "processing": 0,
                    "indexed": 0,
                    "error": 0,
                }
                files_list = []

                for row in rows:
                    status = row.get("status", "uploaded")
                    status_summary[status] = status_summary.get(status, 0) + 1

                    files_list.append({
                        "id": str(row["id"]),
                        "filename": row["filename"],
                        "folder": row["folder"],
                        "status": status,
                        "error_msg": row.get("error_msg"),
                        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                        "indexed_at": row["indexed_at"].isoformat() if row.get("indexed_at") else None,
                    })

                yield f"data: {json.dumps({'type': 'status', 'summary': status_summary, 'files': files_list})}\n\n"

        except asyncio.CancelledError:
            logger.info("[Indexing] SSE клиент отключился")
        except Exception as exc:
            logger.error(f"[Indexing] Ошибка SSE: {exc}")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        _status_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/files")
async def list_indexing_files(
    folder: str | None = None,
    status: str | None = None,
    _user: dict = Depends(get_current_admin),
):
    """
    Список файлов со статусами индексации.
    Можно фильтровать по папке и статусу.
    """
    from src.db.postgres_client import postgres_client as _pg

    base_sql = "SELECT id, filename, folder, file_size, mime_type, status, error_msg, created_at, indexed_at FROM uploaded_files"
    conditions = []
    params: dict = {}

    if folder:
        conditions.append("folder = :folder")
        params["folder"] = folder

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    base_sql += " ORDER BY created_at DESC LIMIT 200"

    rows = await _pg.execute_query(base_sql, params)
    return [
        {
            "id": str(row["id"]),
            "filename": row["filename"],
            "folder": row["folder"],
            "file_size": row.get("file_size"),
            "mime_type": row.get("mime_type"),
            "status": row["status"],
            "error_msg": row.get("error_msg"),
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "indexed_at": row["indexed_at"].isoformat() if row.get("indexed_at") else None,
        }
        for row in rows
    ]


@router.post("/reindex/{file_id}")
async def reindex_file(
    file_id: str,
    _admin: dict = Depends(get_current_admin),
):
    """
    Переиндексация конкретного файла.
    Устанавливает статус в 'uploaded' для повторной обработки.
    """
    from src.db.postgres_client import postgres_client as _pg

    rows = await _pg.execute_query(
        "SELECT id, filename, folder FROM uploaded_files WHERE id = :fid",
        {"fid": file_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Файл не найден")

    file_data = dict(rows[0])
    folder = file_data["folder"]

    # Обновляем статус на uploaded для повторной обработки
    await _pg.execute_query(
        """
        UPDATE uploaded_files
        SET status = 'uploaded', error_msg = NULL, indexed_at = NULL
        WHERE id = :fid
        """,
        {"fid": file_id},
    )

    logger.info(f"[Indexing] Запрошена переиндексация файла: {file_data['filename']}")

    return {
        "message": f"Файл {file_data['filename']} помечен для переиндексации. Запустите индексацию для папки {folder}.",
        "file_id": file_id,
        "folder": folder,
    }
