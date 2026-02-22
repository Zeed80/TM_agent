"""
Роутер администрирования — управление Docker-контейнерами и системой.

Требуется роль 'admin'.
Docker-сокет монтируется в контейнер: /var/run/docker.sock

Endpoints:
  GET  /api/v1/admin/containers                      — список с CPU/RAM статистикой
  GET  /api/v1/admin/containers/{name}/stats         — статистика конкретного контейнера
  POST /api/v1/admin/containers/{name}/restart       — перезапуск
  POST /api/v1/admin/containers/{name}/stop          — остановка
  POST /api/v1/admin/containers/{name}/start         — запуск
  GET  /api/v1/admin/containers/{name}/logs          — SSE поток логов
  GET  /api/v1/admin/system                          — CPU / RAM / диск хоста
  GET  /api/v1/admin/openclaw-setup-token            — токен для входа в OpenClaw Control UI (только admin)
  POST /api/v1/admin/ollama/pull                     — загрузка модели Ollama
  POST /api/v1/admin/compose/rebuild/{service}       — docker compose build + up (pull image)
"""

import asyncio
import json
import logging
import os
import queue as sync_queue
import threading
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.app_settings import get_setting
from src.auth import get_current_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = logging.getLogger(__name__)

# Docker-клиент (синглтон, ленивая инициализация)
_docker_client = None


def _get_docker():
    """Получить Docker-клиент. Поднимает ошибку, если сокет недоступен."""
    global _docker_client
    if _docker_client is None:
        try:
            import docker as docker_sdk
            _docker_client = docker_sdk.DockerClient(base_url="unix:///var/run/docker.sock")
            _docker_client.ping()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Docker-сокет недоступен: {exc}. "
                    "Убедитесь, что /var/run/docker.sock смонтирован в API-контейнер."
                ),
            )
    return _docker_client


# ── Pydantic-модели ───────────────────────────────────────────────────

class ContainerInfo(BaseModel):
    id: str
    name: str
    status: str               # running / exited / paused / restarting
    health: str | None        # healthy / unhealthy / starting / None
    image: str
    created: str
    started_at: str | None
    cpu_percent: float | None
    memory_mb: float | None
    memory_limit_mb: float | None
    memory_percent: float | None
    ports: list[str]


class SystemInfo(BaseModel):
    cpu_count: int
    cpu_percent: float
    memory_total_gb: float
    memory_used_gb: float
    memory_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_percent: float
    uptime_hours: float


class OllamaPullRequest(BaseModel):
    model: str


class OpenClawSetupTokenResponse(BaseModel):
    token: str
    canvas_path: str = "/openclaw/__openclaw__/canvas/"


# ── Вспомогательные функции ───────────────────────────────────────────

def _parse_container_stats(stats: dict) -> dict:
    """Вычисляет CPU% и Memory из сырого ответа Docker stats."""
    cpu_percent = None
    memory_mb = None
    memory_limit_mb = None
    memory_percent = None

    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        num_cpus = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1])
        if system_delta > 0:
            cpu_percent = round((cpu_delta / system_delta) * num_cpus * 100, 2)
    except (KeyError, ZeroDivisionError):
        pass

    try:
        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 1)
        # Вычитаем cache для точного значения
        mem_cache = stats["memory_stats"].get("stats", {}).get("cache", 0)
        actual_usage = mem_usage - mem_cache
        memory_mb = round(actual_usage / 1024 / 1024, 1)
        memory_limit_mb = round(mem_limit / 1024 / 1024, 1)
        memory_percent = round((actual_usage / mem_limit) * 100, 1) if mem_limit > 0 else None
    except (KeyError, ZeroDivisionError):
        pass

    return {
        "cpu_percent": cpu_percent,
        "memory_mb": memory_mb,
        "memory_limit_mb": memory_limit_mb,
        "memory_percent": memory_percent,
    }


def _get_container_info(container, include_stats: bool = False) -> ContainerInfo:
    """Формирует ContainerInfo из Docker container object."""
    client = container

    # Health
    health = None
    try:
        h = container.attrs.get("State", {}).get("Health", {})
        if h:
            health = h.get("Status")
    except Exception:
        pass

    # Ports
    ports: list[str] = []
    try:
        for k, v in (container.ports or {}).items():
            if v:
                for binding in v:
                    ports.append(f"{binding.get('HostPort', '?')}→{k}")
            else:
                ports.append(k)
    except Exception:
        pass

    # Started at
    started_at = None
    try:
        s = container.attrs.get("State", {}).get("StartedAt", "")
        if s and s != "0001-01-01T00:00:00Z":
            started_at = s
    except Exception:
        pass

    # Stats (только для running контейнеров)
    cpu_percent = memory_mb = memory_limit_mb = memory_percent = None
    if include_stats and container.status == "running":
        try:
            raw_stats = container.stats(stream=False)
            parsed = _parse_container_stats(raw_stats)
            cpu_percent = parsed["cpu_percent"]
            memory_mb = parsed["memory_mb"]
            memory_limit_mb = parsed["memory_limit_mb"]
            memory_percent = parsed["memory_percent"]
        except Exception:
            pass

    return ContainerInfo(
        id=container.short_id,
        name=container.name,
        status=container.status,
        health=health,
        image=container.image.tags[0] if container.image.tags else container.image.short_id,
        created=container.attrs.get("Created", ""),
        started_at=started_at,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
        memory_limit_mb=memory_limit_mb,
        memory_percent=memory_percent,
        ports=ports,
    )


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/containers", response_model=list[ContainerInfo])
async def list_containers(
    _admin: dict = Depends(get_current_admin),
) -> list[ContainerInfo]:
    """
    Список всех контейнеров Docker с их статусом.
    Статистика CPU/Memory собирается асинхронно (занимает ~1s на контейнер).
    """
    def _get_all():
        client = _get_docker()
        containers = client.containers.list(all=True)
        # Собираем stats только для running контейнеров
        result = []
        for c in containers:
            result.append(_get_container_info(c, include_stats=(c.status == "running")))
        return result

    return await asyncio.to_thread(_get_all)


@router.get("/containers/{name}/stats", response_model=ContainerInfo)
async def container_stats(
    name: str,
    _admin: dict = Depends(get_current_admin),
) -> ContainerInfo:
    """Статистика конкретного контейнера (CPU%, Memory)."""
    def _get():
        client = _get_docker()
        try:
            container = client.containers.get(name)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Контейнер '{name}' не найден")
        return _get_container_info(container, include_stats=True)

    return await asyncio.to_thread(_get)


@router.post("/containers/{name}/restart", status_code=200)
async def restart_container(
    name: str,
    _admin: dict = Depends(get_current_admin),
) -> dict:
    """Перезапустить контейнер."""
    def _do():
        client = _get_docker()
        try:
            container = client.containers.get(name)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Контейнер '{name}' не найден")
        container.restart(timeout=30)
        return {"status": "restarted", "container": name}

    result = await asyncio.to_thread(_do)
    logger.info(f"[Admin] Перезапущен контейнер: {name}")
    return result


@router.post("/containers/{name}/stop", status_code=200)
async def stop_container(
    name: str,
    _admin: dict = Depends(get_current_admin),
) -> dict:
    """Остановить контейнер."""
    # Запрещаем останавливать критически важные сервисы
    protected = {"nginx", "caddy", "api", "frontend"}
    if name in protected:
        raise HTTPException(
            status_code=400,
            detail=f"Контейнер '{name}' защищён от остановки. Используйте сервер.",
        )

    def _do():
        client = _get_docker()
        try:
            container = client.containers.get(name)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Контейнер '{name}' не найден")
        container.stop(timeout=30)
        return {"status": "stopped", "container": name}

    result = await asyncio.to_thread(_do)
    logger.info(f"[Admin] Остановлен контейнер: {name}")
    return result


@router.post("/containers/{name}/start", status_code=200)
async def start_container(
    name: str,
    _admin: dict = Depends(get_current_admin),
) -> dict:
    """Запустить остановленный контейнер."""
    def _do():
        client = _get_docker()
        try:
            container = client.containers.get(name)
        except Exception:
            raise HTTPException(status_code=404, detail=f"Контейнер '{name}' не найден")
        container.start()
        return {"status": "started", "container": name}

    result = await asyncio.to_thread(_do)
    logger.info(f"[Admin] Запущен контейнер: {name}")
    return result


@router.get("/containers/{name}/logs")
async def stream_container_logs(
    name: str,
    tail: int = 200,
    _admin: dict = Depends(get_current_admin),
) -> StreamingResponse:
    """
    SSE поток логов контейнера.
    Сначала отдаёт последние `tail` строк, затем follow=True.
    """
    return StreamingResponse(
        _logs_generator(name, tail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _logs_generator(name: str, tail: int) -> AsyncGenerator[str, None]:
    """Асинхронный генератор логов контейнера через thread + queue."""
    log_queue: sync_queue.Queue = sync_queue.Queue(maxsize=1000)
    stop_event = threading.Event()
    loop = asyncio.get_event_loop()

    def _reader():
        try:
            client = _get_docker()
            container = client.containers.get(name)
            for chunk in container.logs(
                stream=True,
                follow=True,
                tail=tail,
                timestamps=True,
            ):
                if stop_event.is_set():
                    break
                line = chunk.decode("utf-8", errors="replace").rstrip("\n\r")
                if line:
                    try:
                        log_queue.put_nowait(line)
                    except sync_queue.Full:
                        pass
        except Exception as exc:
            log_queue.put(f"[ERROR] {exc}")
        finally:
            log_queue.put(None)  # Сигнал завершения

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    yield f"data: {json.dumps({'type': 'start', 'container': name})}\n\n"

    try:
        while True:
            try:
                line = await asyncio.wait_for(
                    asyncio.to_thread(log_queue.get, True, 1.0),
                    timeout=35.0,
                )
                if line is None:
                    break
                yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
            except (asyncio.TimeoutError, sync_queue.Empty):
                # Heartbeat чтобы соединение не закрылось
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    except GeneratorExit:
        pass
    finally:
        stop_event.set()
        yield f"data: {json.dumps({'type': 'end'})}\n\n"


# ── Системные метрики ─────────────────────────────────────────────────

@router.get("/system", response_model=SystemInfo)
async def system_info(
    _admin: dict = Depends(get_current_admin),
) -> SystemInfo:
    """Метрики CPU, RAM, диска хоста (через psutil)."""
    def _get():
        cpu_count = psutil.cpu_count(logical=True) or 1
        cpu_percent = psutil.cpu_percent(interval=0.3)

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        boot_time = psutil.boot_time()
        uptime_hours = (time.time() - boot_time) / 3600

        return SystemInfo(
            cpu_count=cpu_count,
            cpu_percent=round(cpu_percent, 1),
            memory_total_gb=round(mem.total / 1024**3, 2),
            memory_used_gb=round(mem.used / 1024**3, 2),
            memory_percent=round(mem.percent, 1),
            disk_total_gb=round(disk.total / 1024**3, 2),
            disk_used_gb=round(disk.used / 1024**3, 2),
            disk_percent=round(disk.percent, 1),
            uptime_hours=round(uptime_hours, 1),
        )

    return await asyncio.to_thread(_get)


# ── OpenClaw: токен для входа в Control UI ────────────────────────────

OPENCLAW_SETUP_TOKEN_PATH = os.environ.get(
    "OPENCLAW_SETUP_TOKEN_PATH",
    "/run/openclaw-setup/gateway.token",
)


@router.get("/openclaw-setup-token", response_model=OpenClawSetupTokenResponse)
async def get_openclaw_setup_token(
    _admin: dict = Depends(get_current_admin),
) -> OpenClawSetupTokenResponse:
    """
    Возвращает токен gateway OpenClaw для входа в Control UI (/openclaw/__openclaw__/canvas/).
    Токен записывается контейнером openclaw в общий volume при старте.
    В Control UI: настройки → поле «Auth» → вставить токен и подключиться.
    """
    try:
        token = await asyncio.to_thread(
            lambda: open(OPENCLAW_SETUP_TOKEN_PATH, "r", encoding="utf-8").read().strip()
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                "Токен OpenClaw пока не создан. Перезапустите контейнер openclaw "
                "(docker compose restart openclaw), подождите ~30 сек и повторите."
            ),
        )
    except OSError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Не удалось прочитать токен OpenClaw: {e}",
        )
    if not token:
        raise HTTPException(
            status_code=404,
            detail="Токен OpenClaw пуст. Перезапустите контейнер openclaw.",
        )
    return OpenClawSetupTokenResponse(token=token, canvas_path="/openclaw/__openclaw__/canvas/")


# ── Ollama: загрузка модели ───────────────────────────────────────────

@router.post("/ollama/pull")
async def pull_ollama_model(
    request: OllamaPullRequest,
    _admin: dict = Depends(get_current_admin),
) -> StreamingResponse:
    """
    Запускает загрузку модели через Ollama API (SSE поток прогресса).
    Модели загружаются в соответствующий контейнер (GPU для LLM/VLM, CPU для embedding/reranker).
    """
    model_name = request.model.strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="Имя модели не указано")

    # Определяем target Ollama (GPU или CPU) по назначениям или env
    from src.ai_engine.model_assignments import get_all_assignments
    assignments = await get_all_assignments()
    gpu_models = {
        (assignments.get("llm") or {}).get("model_id"),
        (assignments.get("vlm") or {}).get("model_id"),
    }
    gpu_models = {m for m in gpu_models if m}
    if not gpu_models:
        gpu_models = {get_setting("llm_model"), get_setting("vlm_model")}
    target_url = get_setting("ollama_gpu_url") if model_name in gpu_models else get_setting("ollama_cpu_url")

    return StreamingResponse(
        _ollama_pull_stream(model_name, target_url),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _ollama_pull_stream(model: str, ollama_url: str) -> AsyncGenerator[str, None]:
    """Стримит прогресс загрузки модели Ollama."""
    yield f"data: {json.dumps({'type': 'start', 'model': model, 'url': ollama_url})}\n\n"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=5.0)) as client:
            async with client.stream(
                "POST",
                f"{ollama_url}/api/pull",
                json={"name": model},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            yield f"data: {json.dumps({'type': 'progress', 'data': data})}\n\n"
                            if data.get("status") == "success":
                                break
                        except json.JSONDecodeError:
                            pass
        yield f"data: {json.dumps({'type': 'done', 'model': model})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"


# ── Запуск ETL задач ──────────────────────────────────────────────────

INGEST_SCRIPTS = {
    "excel":       "src.excel_ingestion",
    "pdf":         "src.pdf_text_ingestion",
    "blueprints":  "src.blueprint_ingestion",
    "techprocess": "src.tech_process_ingestion",
}


@router.post("/ingest/{task}")
async def run_ingestion(
    task: str,
    _admin: dict = Depends(get_current_admin),
) -> StreamingResponse:
    """
    Запускает ETL-задачу через docker exec в контейнере ingestion.
    Результат стримится как SSE.
    """
    if task not in INGEST_SCRIPTS and task != "all":
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная задача '{task}'. Доступные: {', '.join(INGEST_SCRIPTS.keys())}, all",
        )
    return StreamingResponse(
        _run_ingestion_stream(task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_ingestion_stream(task: str) -> AsyncGenerator[str, None]:
    """Запускает ingestion в docker контейнере и стримит вывод."""
    yield f"data: {json.dumps({'type': 'start', 'task': task})}\n\n"

    scripts = list(INGEST_SCRIPTS.values()) if task == "all" else [INGEST_SCRIPTS[task]]

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
