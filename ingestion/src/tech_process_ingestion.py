"""
Tech Process Ingestion — Техпроцессы → граф Neo4j.

Читает Excel/CSV файлы с техпроцессами и формирует граф в Neo4j:
  TechProcess → FOR_PART → Part
  TechProcess → HAS_OPERATION {sequence} → Operation
  Operation → PERFORMED_ON → Machine
  Operation → USES_TOOL → Tool
  Operation → USES_FIXTURE → Mold (опционально)

Ожидаемый формат Excel (documents/tech_processes/):
  Каждый файл = один техпроцесс.
  Колонки: Номер_операции, Наименование_операции, Описание,
           Станок_модель, Станок_тип, Инструмент, Размер_инструмента,
           Оснастка (опционально), Время_уст_мин, Время_маш_мин

Запуск: make ingest-techprocess
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from neo4j import AsyncGraphDatabase
from tqdm import tqdm

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TECH_PROCESSES_DIR = Path(settings.documents_dir) / "tech_processes"


# ── PostgreSQL функция ────────────────────────────────────────────────────

async def update_file_status(
    file_path: str,
    status: str = "indexed",
    error_msg: str | None = None,
):
    """Обновляет статус файла в таблице uploaded_files."""
    import asyncpg

    try:
        conn = await asyncpg.connect(settings.postgres_dsn)
        if status == "indexed":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = NULL, indexed_at = $2
                WHERE file_path = $3
                """,
                status,
                datetime.now(),
                file_path,
            )
        elif status == "processing":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = NULL
                WHERE file_path = $2
                """,
                status,
                file_path,
            )
        elif status == "error":
            await conn.execute(
                """
                UPDATE uploaded_files
                SET status = $1, error_msg = $2, indexed_at = NULL
                WHERE file_path = $3
                """,
                status,
                error_msg,
                file_path,
            )
        await conn.close()
        logger.info(f"Обновлён статус файла {file_path}: {status}")
    except Exception as exc:
        logger.warning(f"Не удалось обновить статус файла {file_path}: {exc}")


# Маппинг колонок Excel → внутренние имена
TECH_PROCESS_COLUMNS = {
    "Номер_операции": "op_number",
    "Наименование_операции": "op_name",
    "Описание": "description",
    "Станок_модель": "machine_model",
    "Станок_тип": "machine_type",   # CNC / UNIVERSAL_LATHE / UNIVERSAL_MILLING / TPA
    "Инструмент": "tool_name",
    "Размер_инструмента": "tool_size",
    "Тип_инструмента": "tool_type",
    "Оснастка": "fixture_name",     # Опционально
    "Время_установки_мин": "setup_time_min",
    "Время_машинное_мин": "machine_time_min",
}

# Маппинг типов станков (для нормализации значений в Excel)
MACHINE_TYPE_MAPPING = {
    "чпу": "CNC",
    "cnc": "CNC",
    "токарный": "UNIVERSAL_LATHE",
    "токарно": "UNIVERSAL_LATHE",
    "фрезерный": "UNIVERSAL_MILLING",
    "фрезерно": "UNIVERSAL_MILLING",
    "тпа": "TPA",
    "термопластавтомат": "TPA",
    "литьевой": "TPA",
}


def _normalize_machine_type(raw_type: str) -> str:
    """Нормализует тип станка к перечислению Neo4j."""
    if not raw_type:
        return "CNC"
    raw_lower = raw_type.lower().strip()
    for key, value in MACHINE_TYPE_MAPPING.items():
        if key in raw_lower:
            return value
    return raw_type.upper()


def _safe_float(val) -> float | None:
    try:
        return float(val) if val and str(val).strip() else None
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    try:
        return int(float(val)) if val and str(val).strip() else None
    except (ValueError, TypeError):
        return None


async def create_tech_process_in_neo4j(
    driver,
    tp_number: str,
    drawing_number: str,
    part_name: str,
    operations: list[dict],
) -> None:
    """
    Атомарно создаёт техпроцесс и все его операции в Neo4j.

    Использует MERGE для идемпотентности (повторный запуск не создаёт дубликатов).
    """
    tp_id = str(uuid.uuid4())

    # Шаг 1: Создать или обновить TechProcess и привязать к Part
    async with driver.session() as session:
        await session.run(
            """
            MERGE (p:Part {drawing_number: $drawing_number})
            ON CREATE SET
                p.id = $part_id,
                p.name = $part_name,
                p.created_at = datetime()

            MERGE (tp:TechProcess {number: $tp_number})
            ON CREATE SET
                tp.id = $tp_id,
                tp.revision = '1',
                tp.status = 'ACTIVE',
                tp.created_at = datetime()
            ON MATCH SET
                tp.status = 'ACTIVE'

            MERGE (tp)-[:FOR_PART]->(p)
            """,
            {
                "drawing_number": drawing_number,
                "part_id": str(uuid.uuid4()),
                "part_name": part_name,
                "tp_number": tp_number,
                "tp_id": tp_id,
            },
        )

        # Шаг 2: Создать операции, станки, инструменты
        for op_data in operations:
            op_id = str(uuid.uuid4())
            machine_id = str(uuid.uuid4())
            tool_id = str(uuid.uuid4())

            await session.run(
                """
                MATCH (tp:TechProcess {number: $tp_number})

                MERGE (op:Operation {number: $op_number, techprocess_number: $tp_number})
                ON CREATE SET
                    op.id = $op_id,
                    op.name = $op_name,
                    op.description = $description,
                    op.setup_time_min = $setup_time,
                    op.machine_time_min = $machine_time

                MERGE (tp)-[:HAS_OPERATION {sequence: $sequence}]->(op)

                WITH op
                MERGE (m:Machine {model: $machine_model})
                ON CREATE SET
                    m.id = $machine_id,
                    m.name = $machine_model,
                    m.type = $machine_type,
                    m.status = 'ACTIVE'

                MERGE (op)-[:PERFORMED_ON]->(m)
                """,
                {
                    "tp_number": tp_number,
                    "op_number": str(op_data["op_number"]),
                    "op_id": op_id,
                    "op_name": op_data.get("op_name", f"Операция {op_data['op_number']}"),
                    "description": op_data.get("description", ""),
                    "setup_time": _safe_float(op_data.get("setup_time_min")),
                    "machine_time": _safe_float(op_data.get("machine_time_min")),
                    "sequence": _safe_int(op_data["op_number"]) or 0,
                    "machine_model": op_data.get("machine_model", "Неизвестный станок"),
                    "machine_id": machine_id,
                    "machine_type": _normalize_machine_type(op_data.get("machine_type", "")),
                },
            )

            # Инструмент (если указан)
            tool_name = op_data.get("tool_name", "").strip()
            if tool_name:
                await session.run(
                    """
                    MATCH (op:Operation {number: $op_number, techprocess_number: $tp_number})
                    MERGE (t:Tool {name: $tool_name, size: $tool_size})
                    ON CREATE SET
                        t.id = $tool_id,
                        t.type = $tool_type
                    MERGE (op)-[:USES_TOOL]->(t)
                    """,
                    {
                        "op_number": str(op_data["op_number"]),
                        "tp_number": tp_number,
                        "tool_name": tool_name,
                        "tool_size": op_data.get("tool_size", ""),
                        "tool_id": tool_id,
                        "tool_type": op_data.get("tool_type", "other"),
                    },
                )

            # Оснастка/пресс-форма (если указана)
            fixture_name = op_data.get("fixture_name", "").strip()
            if fixture_name:
                await session.run(
                    """
                    MATCH (op:Operation {number: $op_number, techprocess_number: $tp_number})
                    MERGE (f:Mold {name: $fixture_name})
                    ON CREATE SET f.id = $fixture_id, f.cavities = 1
                    MERGE (op)-[:USES_FIXTURE]->(f)
                    """,
                    {
                        "op_number": str(op_data["op_number"]),
                        "tp_number": tp_number,
                        "fixture_name": fixture_name,
                        "fixture_id": str(uuid.uuid4()),
                    },
                )


async def ingest_tech_process_file(driver, filepath: Path) -> int:
    """Загружает один файл техпроцесса в Neo4j. Возвращает количество операций."""
    # Читаем Excel/CSV
    if filepath.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(filepath, dtype=str)
    elif filepath.suffix.lower() == ".csv":
        df = pd.read_csv(filepath, dtype=str, encoding="utf-8-sig")
    else:
        return 0

    # Переименовываем колонки
    df = df.rename(columns=TECH_PROCESS_COLUMNS)
    df = df.fillna("")

    if df.empty or "op_number" not in df.columns:
        logger.warning(f"Файл {filepath.name}: нет данных или отсутствует колонка 'Номер_операции'")
        return 0

    # Извлекаем номер техпроцесса из имени файла (например: ТП-001_Корпус.xlsx → ТП-001)
    tp_number = filepath.stem.split("_")[0]
    part_name = "_".join(filepath.stem.split("_")[1:]) if "_" in filepath.stem else filepath.stem
    drawing_number = filepath.stem.replace(" ", "_")

    operations = df.to_dict(orient="records")

    await create_tech_process_in_neo4j(
        driver=driver,
        tp_number=tp_number,
        drawing_number=drawing_number,
        part_name=part_name,
        operations=operations,
    )
    return len(operations)


async def main() -> None:
    logger.info("=== Tech Process Ingestion → Neo4j ===")

    if not TECH_PROCESSES_DIR.exists():
        logger.error(f"Директория не найдена: {TECH_PROCESSES_DIR}")
        return

    supported = {".xlsx", ".xls", ".csv"}
    files = [f for f in TECH_PROCESSES_DIR.rglob("*") if f.suffix.lower() in supported]

    if not files:
        logger.warning(f"Файлы техпроцессов не найдены в {TECH_PROCESSES_DIR}")
        return

    logger.info(f"Найдено файлов: {len(files)}")

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    total_ops = 0
    errors = 0

    try:
        for filepath in tqdm(files, desc="Техпроцессы"):
            file_path_str = str(filepath)
            logger.info(f"  → {filepath.name}")

            try:
                # Обновляем статус на processing
                await update_file_status(file_path_str, "processing")

                ops = await ingest_tech_process_file(driver, filepath)
                total_ops += ops
                logger.info(f"    ✓ Операций загружено: {ops}")

                # Обновляем статус на indexed
                await update_file_status(file_path_str, "indexed")
            except Exception as exc:
                errors += 1
                await update_file_status(file_path_str, "error", str(exc))
                logger.error(f"    ✗ Ошибка {filepath.name}: {exc}")
    finally:
        await driver.close()

    logger.info(f"=== Tech Process Ingestion завершён. Операций: {total_ops}, Ошибок: {errors} ===")


if __name__ == "__main__":
    asyncio.run(main())
