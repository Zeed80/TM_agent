"""
Роутер загрузки файлов через веб-интерфейс.

Endpoint: POST /api/v1/files/upload/{folder}
Все папки принимают любые форматы документов: графика, PDF, Office, CAD и т.д.
Папки: blueprints, invoices, manuals, gosts, emails, catalogs, tech_processes.

Файлы сохраняются в Docker-volume /app/documents/<folder>/
и регистрируются в таблице uploaded_files PostgreSQL.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.auth import get_current_user
from src.app_settings import get_setting
from src.db.postgres_client import postgres_client as _pg

router = APIRouter(prefix="/api/v1/files", tags=["files"])
logger = logging.getLogger(__name__)

# Единый набор разрешённых расширений для всех типов документов (графика, PDF, Office, CAD и т.д.)
_ALLOWED_EXTENSIONS: set[str] = {
    # Графика
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".svg", ".ico",
    # PDF и документы
    ".pdf",
    # Microsoft Office
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # OpenDocument
    ".odt", ".ods", ".odp", ".odg", ".odf", ".odm", ".odb",
    # Текст и таблицы
    ".txt", ".rtf", ".csv", ".md", ".xml",
    # Письма
    ".eml", ".msg",
    # CAD и 3D
    ".dwg", ".dxf", ".step", ".stp", ".stpz", ".iges", ".igs", ".stl", ".3ds", ".obj",
    ".ifc", ".rvt", ".rfa", ".skp", ".fcstd", ".blend", ".max", ".ipt", ".iam",
    ".sldprt", ".sldasm", ".prt", ".asm", ".catpart", ".catproduct",
}

_ALLOWED_FOLDERS: set[str] = {
    "blueprints", "invoices", "manuals", "gosts", "emails", "catalogs", "tech_processes",
}

# Максимальный размер файла: 50 МБ
_MAX_FILE_SIZE = 50 * 1024 * 1024


class UploadedFileResponse(BaseModel):
    id: str
    filename: str
    folder: str
    file_size: int
    status: str
    message: str


class FileListItem(BaseModel):
    id: str
    filename: str
    folder: str
    file_size: int | None
    mime_type: str | None
    status: str
    error_msg: str | None
    created_at: str


@router.post("/upload/{folder}", response_model=UploadedFileResponse, status_code=201)
async def upload_file(
    folder: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> UploadedFileResponse:
    """
    Загрузить файл в директорию документов.
    Файл сохраняется в /app/documents/<folder>/ и регистрируется в БД.
    """
    # Валидация папки
    if folder not in _ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимая папка '{folder}'. "
                   f"Разрешённые: {', '.join(sorted(_ALLOWED_FOLDERS))}",
        )

    # Валидация расширения файла (единый набор для всех папок)
    original_name = file.filename or "unknown"
    suffix = Path(original_name).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый тип файла '{suffix}'. "
                   f"Разрешены форматы документов: графика, PDF, Office, CAD и др.",
        )

    # Читаем файл в память
    content = await file.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Файл пустой.")
    if file_size > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {file_size // (1024*1024)} МБ. Максимум: 50 МБ.",
        )

    # Генерируем безопасное имя файла (uuid + оригинальное расширение)
    safe_filename = f"{uuid.uuid4().hex}{suffix}"
    target_dir = Path(get_setting("documents_base_dir")) / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_filename

    # Сохраняем файл
    try:
        with open(target_path, "wb") as f:
            f.write(content)
    except OSError as exc:
        logger.error(f"[Files] Ошибка записи файла: {exc}")
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {exc}")

    # Регистрируем в БД
    file_id = str(uuid.uuid4())
    await _pg.execute_query(
        """
        INSERT INTO uploaded_files (id, user_id, filename, folder, file_size, mime_type)
        VALUES (:id, :uid, :filename, :folder, :size, :mime)
        """,
        {
            "id": file_id,
            "uid": str(current_user["id"]),
            "filename": safe_filename,
            "folder": folder,
            "size": file_size,
            "mime": file.content_type,
        },
    )

    logger.info(
        f"[Files] Загружен файл: {safe_filename} → {folder}/ "
        f"({file_size // 1024} КБ, пользователь: {current_user['username']})"
    )

    return UploadedFileResponse(
        id=file_id,
        filename=safe_filename,
        folder=folder,
        file_size=file_size,
        status="uploaded",
        message=f"Файл сохранён как {safe_filename}. "
                f"Для индексации запустите: make ingest-{folder.replace('_', '-')}",
    )


@router.get("/list", response_model=list[FileListItem])
async def list_files(
    folder: str | None = None,
    current_user: dict = Depends(get_current_user),
) -> list[FileListItem]:
    """Список загруженных файлов (текущего пользователя или всех для admin)."""
    is_admin = current_user["role"] == "admin"

    base_sql = "SELECT id, filename, folder, file_size, mime_type, status, error_msg, created_at FROM uploaded_files"
    conditions = []
    params: dict = {}

    if not is_admin:
        conditions.append("user_id = :uid")
        params["uid"] = str(current_user["id"])

    if folder:
        if folder not in _ALLOWED_FOLDERS:
            raise HTTPException(status_code=400, detail=f"Недопустимая папка '{folder}'.")
        conditions.append("folder = :folder")
        params["folder"] = folder

    if conditions:
        base_sql += " WHERE " + " AND ".join(conditions)
    base_sql += " ORDER BY created_at DESC LIMIT 200"

    rows = await _pg.execute_query(base_sql, params)
    return [
        FileListItem(
            id=str(row["id"]),
            filename=row["filename"],
            folder=row["folder"],
            file_size=row["file_size"],
            mime_type=row["mime_type"],
            status=row["status"],
            error_msg=row["error_msg"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
        )
        for row in rows
    ]


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """Удалить файл (администратор или владелец)."""
    is_admin = current_user["role"] == "admin"
    condition = "id = :fid" if is_admin else "id = :fid AND user_id = :uid"
    params: dict = {"fid": file_id}
    if not is_admin:
        params["uid"] = str(current_user["id"])

    rows = await _pg.execute_query(
        f"DELETE FROM uploaded_files WHERE {condition} RETURNING id, filename, folder",
        params,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Файл не найден.")

    # Удаляем с диска
    deleted = dict(rows[0])
    file_path = Path(get_setting("documents_base_dir")) / deleted["folder"] / deleted["filename"]
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError as exc:
        logger.warning(f"[Files] Не удалось удалить файл с диска: {exc}")

    logger.info(f"[Files] Удалён файл: {deleted['filename']}")
