"""
Pydantic-модели для навыка graph-search (Text-to-Cypher → Neo4j).
"""

from typing import Any

from pydantic import BaseModel, Field


class GraphSearchRequest(BaseModel):
    """Запрос на поиск по производственному графу."""

    question: str = Field(..., min_length=1, description="Вопрос на естественном языке")


class GeneratedCypherQuery(BaseModel):
    """Сгенерированный LLM Cypher-запрос (валидация перед выполнением в Neo4j)."""

    cypher: str = Field(..., min_length=1)


class GraphSearchResponse(BaseModel):
    """Ответ навыка graph-search: синтезированный текст + сырые данные Neo4j."""

    answer: str
    raw_results: list[dict[str, Any]] = Field(default_factory=list)
    cypher_used: str = ""
    records_count: int = 0
