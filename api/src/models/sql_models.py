"""
Pydantic-модели для навыков: docs-search, inventory-sql, blueprint-vision.
И общая модель сгенерированного SQL (с валидацией только SELECT).
"""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.db.postgres_client import validate_sql


# ─── Docs-search ─────────────────────────────────────────────────────

class DocsSearchRequest(BaseModel):
    """Запрос на семантический поиск по документам."""

    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    source_filter: str | None = None  # опциональный фильтр по source_type


class DocsSearchResponse(BaseModel):
    """Ответ навыка docs-search."""

    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    chunks_found: int = 0


# ─── Inventory-sql (Text-to-SQL) ───────────────────────────────────────

class InventorySearchRequest(BaseModel):
    """Запрос на поиск по складу (Text-to-SQL)."""

    question: str = Field(..., min_length=1)
    use_few_shot: bool = Field(default=True)


class GeneratedSQLQuery(BaseModel):
    """
    Сгенерированный LLM SQL-запрос.
    Только SELECT; валидация через validate_sql перед выполнением.
    """

    sql: str = Field(..., min_length=1)
    params: list[Any] | dict[str, Any] = Field(default_factory=list)
    explanation: str | None = None

    @model_validator(mode="after")
    def check_sql_safe(self) -> "GeneratedSQLQuery":
        validate_sql(self.sql)
        return self


class InventorySearchResponse(BaseModel):
    """Ответ навыка inventory-sql."""

    answer: str
    raw_results: list[dict[str, Any]] = Field(default_factory=list)
    sql_used: str = ""
    rows_count: int = 0


# ─── Blueprint-vision ──────────────────────────────────────────────────

class BlueprintVisionRequest(BaseModel):
    """Запрос на анализ чертежа (VLM или lookup из графа)."""

    image_path: str = Field(..., min_length=1)
    question: str = Field(default="", description="Вопрос или 'полный анализ' для full extraction")


class BlueprintVisionResponse(BaseModel):
    """Ответ навыка blueprint-vision."""

    answer: str
    image_path: str
    source: str = Field(..., description="'graph_cache' или 'vlm_fresh'")


# ─── Norm-control (нормоконтроль) ──────────────────────────────────────

class NormControlRequest(BaseModel):
    """Запрос на проверку документа (нормоконтроль)."""

    document_type: str = Field(..., description="drawing | tech_process")
    identifier: str = Field(default="", description="Номер чертежа или номер техпроцесса")
    image_path: str | None = Field(default=None, description="Путь к файлу чертежа (для drawing, если нет в графе)")


class NormControlCheckItem(BaseModel):
    """Один пункт проверки в отчёте нормоконтроля."""

    name: str = Field(..., description="Название проверки")
    status: str = Field(..., description="passed | failed")
    comment: str = Field(default="", description="Краткий комментарий")


class NormControlResponse(BaseModel):
    """Ответ навыка norm-control."""

    passed: bool = Field(..., description="Нормоконтроль пройден или нет")
    checks: list[NormControlCheckItem] = Field(default_factory=list)
    summary: str = Field(default="", description="Итоговое заключение")
    document_info: dict[str, Any] = Field(default_factory=dict, description="Краткие данные документа (опционально)")
