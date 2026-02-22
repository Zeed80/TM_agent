"""
VRAM Manager — управление памятью RTX 3090 (24GB).

Проблема: Qwen3:30b (Q4_K_M) ≈ 18GB + Qwen3-VL:14b (Q4_K_M) ≈ 9GB > 24GB.
Решение: asyncio.Lock гарантирует, что LLM и VLM никогда не загружены одновременно.

Embedding и Reranker работают на ollama-cpu → не конкурируют за VRAM.

Правило 1: все HTTP-таймауты к Ollama GPU = 120 секунд (переключение моделей).
Правило 2: num_ctx=16384 выставляется при каждой загрузке модели.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class VRAMManager:
    """
    Синглтон-менеджер VRAM.

    Использование:
        vram = VRAMManager()

        # Перед каждым LLM-запросом (graph-search, docs-search, sql):
        await vram.ensure_llm()
        result = await llm_client.generate(...)

        # Для VLM-запроса (blueprint-vision):
        async with vram.use_vlm():
            result = await vlm_client.analyze(image_b64)
    """

    _instance: "VRAMManager | None" = None
    _lock: asyncio.Lock
    _current_model: str | None
    _initialized: bool

    def __new__(cls) -> "VRAMManager":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._lock = asyncio.Lock()
            instance._current_model = None
            instance._initialized = False
            cls._instance = instance
        return cls._instance

    @property
    def current_model(self) -> str | None:
        return self._current_model

    async def warm_up_llm(self) -> None:
        """
        Вызывается при старте FastAPI (lifespan).
        Загружает LLM в VRAM с keep_alive=-1 (не выгружать автоматически).
        По умолчанию использует settings.llm_model.
        """
        await self.warm_up_llm_with_model(settings.llm_model)

    async def warm_up_llm_with_model(self, model_id: str) -> None:
        """
        Прогрев указанной LLM-модели в VRAM.
        Используется при старте, если назначение из реестра — Ollama GPU.
        """
        if self._initialized:
            logger.info("[VRAM] Уже инициализирован, пропускаем прогрев")
            return

        logger.info(f"[VRAM] Прогрев LLM: {model_id} (num_ctx={settings.llm_num_ctx})")
        await self._load_model(
            model=model_id,
            num_ctx=settings.llm_num_ctx,
        )
        self._current_model = model_id
        self._initialized = True
        logger.info(f"[VRAM] LLM готова: {model_id}")

    async def ensure_llm(self) -> None:
        """
        Гарантирует, что LLM активна в VRAM перед запросом.

        Если LLM уже загружена — возвращается немедленно (без блокировки).
        Если VLM загружена — ждёт освобождения Lock, затем переключается.
        """
        await self.ensure_llm_for_model(settings.llm_model)

    async def ensure_llm_for_model(self, model_id: str) -> None:
        """
        Гарантирует, что в VRAM загружена указанная LLM-модель.
        Используется реестром при выборе модели из назначений.
        """
        if self._current_model == model_id:
            return
        logger.info("[VRAM] LLM не активна — ожидаю освобождения Lock для переключения")
        async with self._lock:
            if self._current_model != model_id:
                await self._swap_to(
                    target_model=model_id,
                    num_ctx=settings.llm_num_ctx,
                )

    @asynccontextmanager
    async def use_vlm(self) -> AsyncIterator[None]:
        """
        Контекст-менеджер для blueprint-vision навыка.

        Правило 1: блокирует другие GPU-запросы на время работы VLM.
        Гарантирует восстановление LLM в блоке finally (даже при ошибке VLM).

        Пример использования:
            async with vram_manager.use_vlm():
                result = await vlm_client.analyze_blueprint(image_b64)
        """
        async with self.use_vlm_for_model(settings.vlm_model) as _:
            yield

    @asynccontextmanager
    async def use_vlm_for_model(self, vlm_model_id: str) -> AsyncIterator[None]:
        """
        Контекст-менеджер для VLM с указанной моделью.
        В finally восстанавливает LLM из назначений (если провайдер ollama_gpu).
        """
        from src.ai_engine.model_assignments import get_assignment

        assignment = await get_assignment("llm")
        restore_model: str | None = None
        if assignment.get("provider_type") == "ollama_gpu":
            restore_model = (assignment.get("model_id") or "").strip() or settings.llm_model

        logger.info("[VRAM] Запрос на VLM — ожидаю Lock...")
        async with self._lock:
            logger.info("[VRAM] Lock получен — переключаюсь на VLM")
            try:
                await self._swap_to(
                    target_model=vlm_model_id,
                    num_ctx=settings.vlm_num_ctx,
                )
                logger.info("[VRAM] VLM активна — передаю управление")
                yield
            finally:
                logger.info("[VRAM] VLM завершила работу — восстанавливаю LLM")
                if restore_model:
                    await self._swap_to(
                        target_model=restore_model,
                        num_ctx=settings.llm_num_ctx,
                    )
                    logger.info("[VRAM] LLM восстановлена")
        # Lock освобождён автоматически после выхода из блока async with

    async def _swap_to(self, target_model: str, num_ctx: int) -> None:
        """
        Внутренний метод: выгрузить текущую модель и загрузить target_model.

        Правило 1: connect=10s, read/write=120s (переключение занимает 60-90 сек).
        Правило 2: num_ctx передаётся при каждой загрузке.
        """
        _timeout = httpx.Timeout(
            connect=10.0,
            read=settings.vram_swap_timeout,
            write=settings.vram_swap_timeout,
            pool=5.0,
        )

        async with httpx.AsyncClient(timeout=_timeout) as client:
            # ── Шаг 1: Выгрузить текущую модель ─────────────────────
            if self._current_model and self._current_model != target_model:
                logger.info(f"[VRAM] Выгрузка модели: {self._current_model}")
                try:
                    await client.post(
                        f"{settings.ollama_gpu_url}/api/generate",
                        json={
                            "model": self._current_model,
                            "prompt": "",
                            "keep_alive": "0s",  # Немедленная выгрузка из VRAM
                        },
                    )
                    logger.info(f"[VRAM] Выгружена: {self._current_model}")
                except httpx.HTTPError as exc:
                    logger.warning(
                        f"[VRAM] Ошибка выгрузки {self._current_model}: {exc}. "
                        "Продолжаю загрузку новой модели."
                    )

            # ── Шаг 2: Загрузить целевую модель ──────────────────────
            # Пустой warm-up запрос с keep_alive=-1 принуждает Ollama
            # загрузить модель в VRAM и держать её бессрочно.
            logger.info(
                f"[VRAM] Загрузка в VRAM: {target_model} "
                f"(num_ctx={num_ctx}, keep_alive=-1)"
            )
            await client.post(
                f"{settings.ollama_gpu_url}/api/generate",
                json={
                    "model": target_model,
                    "prompt": "",
                    "keep_alive": "-1",
                    "options": {
                        "num_ctx": num_ctx,  # Правило 2
                    },
                },
            )
            self._current_model = target_model
            logger.info(f"[VRAM] Загружена: {target_model}")

    async def _load_model(self, model: str, num_ctx: int) -> None:
        """Загрузить модель с нуля (без предварительной выгрузки)."""
        _timeout = httpx.Timeout(
            connect=10.0,
            read=settings.vram_swap_timeout,
            write=settings.vram_swap_timeout,
            pool=5.0,
        )
        async with httpx.AsyncClient(timeout=_timeout) as client:
            await client.post(
                f"{settings.ollama_gpu_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "keep_alive": "-1",
                    "options": {"num_ctx": num_ctx},
                },
            )
