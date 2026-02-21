# ═══════════════════════════════════════════════════════════════════
# Enterprise AI Assistant — Python FastAPI
# Python 3.12-slim + uv (Rust-based package manager, 10-20x faster than pip)
# src/ монтируется как volume в docker-compose.yml →
# uvicorn --reload обеспечивает горячую перезагрузку без rebuild
# ═══════════════════════════════════════════════════════════════════

FROM python:3.12-slim

# Копируем uv бинарник из официального образа Astral
# Не нужно pip install uv — нет накладных расходов, всегда последняя версия
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Системные зависимости:
# - curl: health check
# - libpq-dev: asyncpg нативные расширения
# - gcc / g++: компиляция нативных модулей (fastembed, asyncpg, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# UV настройки для Docker:
# UV_SYSTEM_PYTHON=1  — устанавливает в системный Python (не venv)
# UV_NO_CACHE=1       — не кэшировать в образе (кэш = размер слоя)
# UV_COMPILE_BYTECODE=1 — pre-compile .pyc → быстрее старт контейнера
ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Сначала копируем только requirements.txt — кэш Docker-слоя.
# Если requirements.txt не изменился, uv не перезапускается.
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Копируем src/ в образ (будет переопределён volume mount в dev-режиме)
COPY src/ ./src/

EXPOSE 8000

# --reload-dir гарантирует, что uvicorn следит именно за /app/src
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--reload", \
     "--reload-dir", "/app/src"]
