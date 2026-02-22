"""
Базовые протоколы (интерфейсы) для провайдеров моделей.

Все провайдеры (Ollama, OpenAI, vLLM и т.д.) реализуют эти интерфейсы,
чтобы реестр мог вызывать их единообразно.
"""

from typing import Any, Protocol


class LLMProviderProtocol(Protocol):
    """Провайдер текстовой генерации (LLM)."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        top_p: float = 0.9,
        stop: list[str] | None = None,
    ) -> str: ...

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str: ...


class VLMProviderProtocol(Protocol):
    """Провайдер мультимодальной модели (vision + text)."""

    async def analyze_blueprint(
        self,
        image_path: str | Any,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...

    async def analyze_blueprint_from_bytes(
        self,
        image_bytes: bytes,
        image_format: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...


class EmbeddingProviderProtocol(Protocol):
    """Провайдер эмбеддингов."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_single(self, text: str) -> list[float]: ...


class RerankerProviderProtocol(Protocol):
    """Провайдер переранжирования (cross-encoder)."""

    async def rerank_batch(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]: ...

    def sort_by_scores(
        self,
        items: list,
        scores: list[float],
        top_k: int | None = None,
    ) -> list: ...
