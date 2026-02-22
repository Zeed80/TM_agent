"""
Провайдеры Ollama: LLM, VLM, Embedding, Reranker.

Используют url и model_id из назначения (config["url"], model_id).
VRAMManager применяется только для GPU (LLM/VLM).
"""

import base64
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from src.app_settings import get_setting
from src.ai_engine.vram_manager import VRAMManager

logger = logging.getLogger(__name__)


def _llm_timeout() -> httpx.Timeout:
    t = get_setting("llm_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)


def _vlm_timeout() -> httpx.Timeout:
    t = get_setting("vlm_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)


def _embed_timeout() -> httpx.Timeout:
    t = get_setting("embedding_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)


def _rerank_timeout() -> httpx.Timeout:
    t = get_setting("reranker_timeout")
    return httpx.Timeout(connect=10.0, read=t, write=t, pool=5.0)

_RERANK_PROMPT_TEMPLATE = (
    "Given a query and a document, determine if the document is relevant to the query.\n"
    "Answer with a relevance score between 0.0 and 1.0, where:\n"
    "  1.0 = highly relevant\n"
    "  0.0 = not relevant\n\n"
    "Query: {query}\n\n"
    "Document:\n{document}\n\n"
    "Relevance score (respond with only a decimal number between 0.0 and 1.0):"
)


def _parse_rerank_score(text: str) -> float:
    text = text.strip().lower()
    if text.startswith("yes"):
        return 0.9
    if text.startswith("no"):
        return 0.1
    numbers = re.findall(r"\b(0\.\d+|1\.0|1)\b", text)
    if numbers:
        return min(1.0, max(0.0, float(numbers[0])))
    logger.warning(f"[Reranker] Не удалось распарсить score из: '{text[:100]}', используем 0.5")
    return 0.5


class OllamaLLMProvider:
    """LLM через Ollama (GPU). Использует VRAMManager."""

    def __init__(self, url: str, model_id: str):
        self._url = url.rstrip("/")
        self._model_id = model_id
        self._num_ctx = get_setting("llm_num_ctx")

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        top_p: float = 0.9,
        stop: list[str] | None = None,
    ) -> str:
        vram = VRAMManager()
        await vram.ensure_llm_for_model(self._model_id)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": self._num_ctx,
                "temperature": temperature,
                "top_p": top_p,
                "repeat_penalty": 1.1,
            },
        }
        if stop:
            body["options"] = body.get("options", {}) | {"stop": stop}

        async with httpx.AsyncClient(timeout=_llm_timeout()) as client:
            resp = await client.post(f"{self._url}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> str:
        vram = VRAMManager()
        await vram.ensure_llm_for_model(self._model_id)

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=_llm_timeout()) as client:
            resp = await client.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model_id,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "num_ctx": self._num_ctx,
                        "temperature": 0.0,
                        "repeat_penalty": 1.1,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()


class OllamaVLMProvider:
    """VLM через Ollama GPU. Использует VRAMManager.use_vlm()."""

    def __init__(self, url: str, model_id: str):
        self._url = url.rstrip("/")
        self._model_id = model_id
        self._num_ctx = get_setting("vlm_num_ctx")

    @staticmethod
    def _encode_image(image_path: str | Path) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def analyze_blueprint(
        self,
        image_path: str | Path,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        vram = VRAMManager()
        image_b64 = self._encode_image(image_path)
        async with vram.use_vlm_for_model(self._model_id):
            async with httpx.AsyncClient(timeout=_vlm_timeout()) as client:
                resp = await client.post(
                    f"{self._url}/api/chat",
                    json={
                        "model": self._model_id,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt, "images": [image_b64]},
                        ],
                        "stream": False,
                        "options": {"num_ctx": self._num_ctx, "temperature": 0.0, "repeat_penalty": 1.1},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()

    async def analyze_blueprint_from_bytes(
        self,
        image_bytes: bytes,
        image_format: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        vram = VRAMManager()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        async with vram.use_vlm_for_model(self._model_id):
            async with httpx.AsyncClient(timeout=_vlm_timeout()) as client:
                resp = await client.post(
                    f"{self._url}/api/chat",
                    json={
                        "model": self._model_id,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt, "images": [image_b64]},
                        ],
                        "stream": False,
                        "options": {"num_ctx": self._num_ctx, "temperature": 0.0},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()


class OllamaEmbeddingProvider:
    """Embedding через Ollama CPU."""

    def __init__(self, url: str, model_id: str):
        self._url = url.rstrip("/")
        self._model_id = model_id

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=_embed_timeout()) as client:
            resp = await client.post(
                f"{self._url}/api/embed",
                json={"model": self._model_id, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("embeddings", [])

    async def embed_single(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=_embed_timeout()) as client:
            resp = await client.post(
                f"{self._url}/api/embeddings",
                json={"model": self._model_id, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("embedding", [])


class OllamaRerankerProvider:
    """Reranker через Ollama CPU."""

    def __init__(self, url: str, model_id: str):
        self._url = url.rstrip("/")
        self._model_id = model_id

    async def rerank_batch(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        scores: list[float] = []
        for doc in documents:
            prompt = _RERANK_PROMPT_TEMPLATE.format(
                query=query,
                document=doc[:2000],
            )
            async with httpx.AsyncClient(timeout=_rerank_timeout()) as client:
                resp = await client.post(
                    f"{self._url}/api/generate",
                    json={
                        "model": self._model_id,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0, "num_predict": 10, "top_k": 1},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            raw = (data.get("response") or "").strip()
            scores.append(_parse_rerank_score(raw))
        return scores

    @staticmethod
    def sort_by_scores(
        items: list,
        scores: list[float],
        top_k: int | None = None,
    ) -> list:
        paired = sorted(zip(scores, items), key=lambda x: x[0], reverse=True)
        if top_k is not None:
            paired = paired[:top_k]
        return [item for _, item in paired]
