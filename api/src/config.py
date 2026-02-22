from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Конфигурация приложения.
    Значения загружаются из переменных окружения (docker-compose environment:).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Ollama ──────────────────────────────────────────────────────
    ollama_gpu_url: str = "http://ollama-gpu:11434"
    ollama_cpu_url: str = "http://ollama-cpu:11434"

    # ── Модели ──────────────────────────────────────────────────────
    llm_model: str = "qwen3:30b"
    vlm_model: str = "qwen3-vl:14b"
    embedding_model: str = "qwen3-embedding"
    reranker_model: str = "qwen3-reranker"

    # Правило 2: num_ctx обязателен минимум 16384 для RAG
    llm_num_ctx: int = 16384
    vlm_num_ctx: int = 16384

    # Правило 1: таймауты 120 секунд на все LLM/VLM вызовы
    llm_timeout: float = 120.0
    vlm_timeout: float = 120.0
    embedding_timeout: float = 60.0
    reranker_timeout: float = 60.0
    # Таймаут переключения модели в VRAM (выгрузка + загрузка)
    vram_swap_timeout: float = 120.0

    # ── Neo4j ───────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change_me"

    # ── Qdrant ──────────────────────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "documents"

    # Правило 3: размерность dense-вектора qwen3-embedding.
    # Уточни после `ollama pull qwen3-embedding`:
    #   docker compose exec ollama-cpu ollama show qwen3-embedding --verbose
    embedding_dim: int = 4096

    # Имена векторов внутри коллекции Qdrant
    qdrant_dense_vector_name: str = "dense"
    qdrant_sparse_vector_name: str = "bm25"

    # Количество результатов для prefetch (dense + sparse) перед RRF-слиянием
    qdrant_prefetch_limit: int = 20
    # Финальное количество результатов после RRF + reranking
    qdrant_final_limit: int = 5

    # ── PostgreSQL ──────────────────────────────────────────────────
    postgres_dsn: str = (
        "postgresql+asyncpg://enterprise:change_me@postgres:5432/enterprise_ai"
    )

    # ── JWT Authentication ──────────────────────────────────────────
    jwt_secret_key: str = "change-me-to-a-very-long-random-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # Шифрование API-ключей провайдеров в БД (задаются через админку, не .env).
    # Если не задано — используется jwt_secret_key (минимум 32 байта для Fernet).
    provider_keys_encryption_secret: str | None = None

    # ── Web UI / File Upload ────────────────────────────────────────
    # Директория для хранения загруженных документов
    documents_base_dir: str = "/app/documents"

    # ── CORS — разрешённые origins для React фронтенда ─────────────
    # Список через запятую: https://example.com,https://192.168.1.100
    cors_origins: str = "*"

    # ── Agentic Loop — лимит итераций вызова инструментов ──────────
    chat_max_tool_iterations: int = 5

    # ── Облачные провайдеры (опционально) ───────────────────────────
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    minimax_api_key: str | None = None
    # Таймауты для облачных вызовов (секунды)
    cloud_llm_timeout: float = 120.0
    cloud_embedding_timeout: float = 60.0

    # ── vLLM (локальный, OpenAI-совместимый API) ─────────────────────
    vllm_base_url: str | None = None  # например http://vllm:8000/v1


settings = Settings()
