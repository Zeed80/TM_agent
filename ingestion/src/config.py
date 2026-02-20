"""Конфигурация ingestion-сервиса (идентична api/src/config.py, но без FastAPI-зависимостей)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_gpu_url: str = "http://ollama-gpu:11434"
    ollama_cpu_url: str = "http://ollama-cpu:11434"

    llm_model: str = "qwen3:30b"
    vlm_model: str = "qwen3-vl:14b"
    embedding_model: str = "qwen3-embedding"

    llm_num_ctx: int = 16384
    vlm_num_ctx: int = 16384

    vlm_timeout: float = 120.0
    embedding_timeout: float = 60.0
    llm_timeout: float = 120.0

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change_me"

    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "documents"
    embedding_dim: int = 4096
    qdrant_dense_vector_name: str = "dense"
    qdrant_sparse_vector_name: str = "bm25"

    postgres_dsn: str = (
        "postgresql+asyncpg://enterprise:change_me@postgres:5432/enterprise_ai"
    )

    # Директория с документами внутри контейнера
    documents_dir: str = "/app/documents"

    # Размер чанка текста для Qdrant (в символах)
    chunk_size: int = 1000
    chunk_overlap: int = 200


settings = IngestionSettings()
