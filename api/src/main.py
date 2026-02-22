import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.ai_engine.vram_manager import VRAMManager
from src.app_settings import get_setting, load_from_db
from src.config import settings
from src.db.neo4j_client import neo4j_client
from src.db.postgres_client import postgres_client
from src.db.qdrant_client import qdrant_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    Подключает все клиенты и прогревает LLM в VRAM при старте.
    Корректно закрывает соединения при shutdown.
    """
    logger.info("=== Enterprise AI Assistant API — Запуск ===")

    logger.info("Подключение к Neo4j...")
    await neo4j_client.connect()

    logger.info("Подключение к PostgreSQL...")
    await postgres_client.connect()

    logger.info("Загрузка настроек из БД...")
    await load_from_db()

    logger.info("Подключение к Qdrant...")
    await qdrant_client.connect()

    logger.info("Проверка коллекции Qdrant (Hybrid Search: BM25 + Dense)...")
    await qdrant_client.ensure_collection()

    logger.info("Прогрев LLM в VRAM (это может занять до 60 секунд)...")
    vram = VRAMManager()
    from src.ai_engine.model_assignments import get_assignment
    llm_assignment = await get_assignment("llm")
    if (llm_assignment.get("provider_type") or "").strip().lower() == "ollama_gpu":
        model_id = (llm_assignment.get("model_id") or "").strip() or get_setting("llm_model")
        await vram.warm_up_llm_with_model(model_id)
    else:
        await vram.warm_up_llm()

    logger.info("=== Все системы готовы. API принимает запросы. ===")

    yield

    logger.info("Завершение работы — закрытие соединений...")
    await neo4j_client.close()
    await postgres_client.close()
    await qdrant_client.close()
    logger.info("=== Enterprise AI Assistant API — Остановлен ===")


app = FastAPI(
    title="Enterprise AI Assistant API",
    description=(
        "Python FastAPI микросервис. "
        "Навыки: graph-search (Neo4j), docs-search (Qdrant), "
        "blueprint-vision (VLM), inventory-sql (PostgreSQL). "
        "Web UI: JWT-auth, chat с agentic loop, загрузка файлов."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS — регистрируется при создании приложения (middleware нельзя добавлять после старта).
# Значение берётся из get_setting (при первом запуске — из .env, т.к. БД ещё не загружена).
# Изменение CORS в Web UI вступит в силу после перезапуска API.
_cors_origins = [o.strip() for o in (get_setting("cors_origins") or "").split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health & root ─────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/", tags=["system"])
async def root() -> JSONResponse:
    vram = VRAMManager()
    return JSONResponse({
        "service": "Enterprise AI Assistant API",
        "version": "2.0.0",
        "docs": "/docs",
        "vram_current_model": vram.current_model,
    })


# ── Навыки (OpenClaw / внутренние) ───────────────────────────────────
from src.routers import graph_search, docs_search, blueprint_vision, inventory_sql  # noqa: E402

app.include_router(graph_search.router, prefix="/skills")
app.include_router(docs_search.router, prefix="/skills")
app.include_router(blueprint_vision.router, prefix="/skills")
app.include_router(inventory_sql.router, prefix="/skills")

# ── Web API (авторизованные) ─────────────────────────────────────────
from src.routers import auth_router, chat_router, files_router, system_router, admin_router, models_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(files_router.router)
app.include_router(system_router.router)
app.include_router(models_router.router)
app.include_router(admin_router.router)
from src.routers import settings_router  # noqa: E402
app.include_router(settings_router.router)
