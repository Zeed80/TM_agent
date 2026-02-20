"""
Excel/CSV Ingestion → PostgreSQL.

Читает каталоги инструмента, металлов и полимеров из Excel/CSV файлов
из папки documents/catalogs/ и загружает в PostgreSQL.

Запуск: make ingest-excel
  или: docker compose --profile ingestion run --rm ingestion python -m src.excel_ingestion

Ожидаемая структура файлов (documents/catalogs/):
  - tools_*.xlsx      → tools_catalog
  - metals_*.xlsx     → metals_catalog
  - polymers_*.xlsx   → polymers_catalog
  - inventory_*.xlsx  → inventory (остатки)
"""

import asyncio
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from tqdm import tqdm

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CATALOGS_DIR = Path(settings.documents_dir) / "catalogs"


# ── Маппинг колонок Excel → БД ────────────────────────────────────────────────

TOOLS_COLUMNS = {
    "Наименование": "name",
    "Тип": "type",
    "Размер": "size",
    "ГОСТ": "gost",
    "Производитель": "manufacturer",
    "Покрытие": "coating",
    "Материал инструмента": "material",
}

METALS_COLUMNS = {
    "Наименование": "name",
    "ГОСТ": "gost",
    "Марка": "grade",
    "Плотность, г/см3": "density_g_cm3",
    "Твёрдость HB": "hardness_hb",
    "Предел прочности, МПа": "tensile_strength_mpa",
    "Предел текучести, МПа": "yield_strength_mpa",
    "Относительное удлинение, %": "elongation_pct",
}

POLYMERS_COLUMNS = {
    "Наименование": "name",
    "Марка": "grade",
    "Производитель": "manufacturer",
    "ПТР, г/10 мин": "mfi_g_10min",
    "Плотность, г/см3": "density_g_cm3",
    "Т плавления, °C": "melting_temp_c",
    "Т переработки мин, °C": "processing_temp_min_c",
    "Т переработки макс, °C": "processing_temp_max_c",
    "Т формы мин, °C": "mold_temp_min_c",
    "Т формы макс, °C": "mold_temp_max_c",
    "Давление литья, бар": "injection_pressure_bar",
    "Усадка, %": "shrinkage_pct",
    "Влажность макс, %": "moisture_content_max",
    "Т сушки, °C": "drying_temp_c",
    "Время сушки, ч": "drying_time_h",
}


def _read_excel_or_csv(filepath: Path) -> pd.DataFrame:
    """Читает Excel или CSV файл в DataFrame."""
    if filepath.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(filepath, dtype=str)
    elif filepath.suffix.lower() == ".csv":
        return pd.read_csv(filepath, dtype=str, encoding="utf-8-sig")
    else:
        raise ValueError(f"Неподдерживаемый формат: {filepath.suffix}")


def _rename_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Переименовывает колонки по маппингу, отбрасывает неизвестные."""
    df = df.rename(columns=mapping)
    known_cols = list(mapping.values())
    existing_cols = [c for c in known_cols if c in df.columns]
    return df[existing_cols]


async def ingest_tools(engine) -> int:
    """Загружает каталог инструмента в tools_catalog."""
    files = list(CATALOGS_DIR.glob("tools_*.xlsx")) + list(CATALOGS_DIR.glob("tools_*.csv"))
    if not files:
        logger.warning(f"Файлы tools_*.xlsx/csv не найдены в {CATALOGS_DIR}")
        return 0

    total = 0
    for filepath in files:
        logger.info(f"  Обрабатываю: {filepath.name}")
        df = _read_excel_or_csv(filepath)
        df = _rename_columns(df, TOOLS_COLUMNS)
        df = df.dropna(subset=["name"]).fillna("")

        async with engine.begin() as conn:
            for _, row in tqdm(df.iterrows(), total=len(df), desc=filepath.stem):
                await conn.execute(
                    text(
                        """
                        INSERT INTO tools_catalog (name, type, size, gost, manufacturer, coating, material)
                        VALUES (:name, :type, :size, :gost, :manufacturer, :coating, :material)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "name": row.get("name", ""),
                        "type": row.get("type", "other"),
                        "size": row.get("size", ""),
                        "gost": row.get("gost", ""),
                        "manufacturer": row.get("manufacturer", ""),
                        "coating": row.get("coating", "none"),
                        "material": row.get("material", ""),
                    },
                )
                total += 1

    return total


async def ingest_metals(engine) -> int:
    """Загружает каталог металлов в metals_catalog."""
    files = list(CATALOGS_DIR.glob("metals_*.xlsx")) + list(CATALOGS_DIR.glob("metals_*.csv"))
    if not files:
        logger.warning(f"Файлы metals_*.xlsx/csv не найдены в {CATALOGS_DIR}")
        return 0

    total = 0
    for filepath in files:
        logger.info(f"  Обрабатываю: {filepath.name}")
        df = _read_excel_or_csv(filepath)
        df = _rename_columns(df, METALS_COLUMNS)
        df = df.dropna(subset=["name", "gost", "grade"]).fillna("")

        def safe_int(val):
            try:
                return int(float(val)) if val else None
            except (ValueError, TypeError):
                return None

        def safe_float(val):
            try:
                return float(val) if val else None
            except (ValueError, TypeError):
                return None

        async with engine.begin() as conn:
            for _, row in tqdm(df.iterrows(), total=len(df), desc=filepath.stem):
                await conn.execute(
                    text(
                        """
                        INSERT INTO metals_catalog
                          (name, gost, grade, density_g_cm3, hardness_hb,
                           tensile_strength_mpa, yield_strength_mpa, elongation_pct)
                        VALUES
                          (:name, :gost, :grade, :density, :hb, :tensile, :yield_s, :elong)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "name": row.get("name", ""),
                        "gost": row.get("gost", ""),
                        "grade": row.get("grade", ""),
                        "density": safe_float(row.get("density_g_cm3")),
                        "hb": safe_int(row.get("hardness_hb")),
                        "tensile": safe_int(row.get("tensile_strength_mpa")),
                        "yield_s": safe_int(row.get("yield_strength_mpa")),
                        "elong": safe_float(row.get("elongation_pct")),
                    },
                )
                total += 1

    return total


async def ingest_polymers(engine) -> int:
    """Загружает каталог полимеров в polymers_catalog."""
    files = list(CATALOGS_DIR.glob("polymers_*.xlsx")) + list(CATALOGS_DIR.glob("polymers_*.csv"))
    if not files:
        logger.warning(f"Файлы polymers_*.xlsx/csv не найдены в {CATALOGS_DIR}")
        return 0

    total = 0
    for filepath in files:
        logger.info(f"  Обрабатываю: {filepath.name}")
        df = _read_excel_or_csv(filepath)
        df = _rename_columns(df, POLYMERS_COLUMNS)
        df = df.dropna(subset=["name", "grade"]).fillna("")

        def safe_int(val):
            try:
                return int(float(val)) if val else None
            except (ValueError, TypeError):
                return None

        def safe_float(val):
            try:
                return float(val) if val else None
            except (ValueError, TypeError):
                return None

        async with engine.begin() as conn:
            for _, row in tqdm(df.iterrows(), total=len(df), desc=filepath.stem):
                await conn.execute(
                    text(
                        """
                        INSERT INTO polymers_catalog
                          (name, grade, manufacturer, mfi_g_10min, density_g_cm3,
                           melting_temp_c, processing_temp_min_c, processing_temp_max_c,
                           mold_temp_min_c, mold_temp_max_c, injection_pressure_bar,
                           shrinkage_pct, moisture_content_max, drying_temp_c, drying_time_h)
                        VALUES
                          (:name, :grade, :mfr, :mfi, :density,
                           :melt, :proc_min, :proc_max,
                           :mold_min, :mold_max, :inj_press,
                           :shrink, :moisture, :dry_t, :dry_h)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "name": row.get("name", ""),
                        "grade": row.get("grade", ""),
                        "mfr": row.get("manufacturer", ""),
                        "mfi": safe_float(row.get("mfi_g_10min")),
                        "density": safe_float(row.get("density_g_cm3")),
                        "melt": safe_int(row.get("melting_temp_c")),
                        "proc_min": safe_int(row.get("processing_temp_min_c")),
                        "proc_max": safe_int(row.get("processing_temp_max_c")),
                        "mold_min": safe_int(row.get("mold_temp_min_c")),
                        "mold_max": safe_int(row.get("mold_temp_max_c")),
                        "inj_press": safe_int(row.get("injection_pressure_bar")),
                        "shrink": safe_float(row.get("shrinkage_pct")),
                        "moisture": safe_float(row.get("moisture_content_max")),
                        "dry_t": safe_int(row.get("drying_temp_c")),
                        "dry_h": safe_float(row.get("drying_time_h")),
                    },
                )
                total += 1

    return total


async def main() -> None:
    logger.info("=== Excel/CSV Ingestion → PostgreSQL ===")
    logger.info(f"Каталог документов: {CATALOGS_DIR}")

    if not CATALOGS_DIR.exists():
        logger.error(f"Директория не найдена: {CATALOGS_DIR}")
        logger.info(f"Создай папку и помести файлы: {CATALOGS_DIR}")
        return

    engine = create_async_engine(settings.postgres_dsn, echo=False)

    try:
        logger.info("→ Загрузка каталога инструмента...")
        tools_count = await ingest_tools(engine)
        logger.info(f"  ✓ Инструменты: {tools_count} записей")

        logger.info("→ Загрузка каталога металлов...")
        metals_count = await ingest_metals(engine)
        logger.info(f"  ✓ Металлы: {metals_count} записей")

        logger.info("→ Загрузка каталога полимеров...")
        polymers_count = await ingest_polymers(engine)
        logger.info(f"  ✓ Полимеры: {polymers_count} записей")

        logger.info(f"=== Загрузка завершена. Итого: {tools_count + metals_count + polymers_count} записей ===")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
