# ═══════════════════════════════════════════════════════════════════
# Enterprise AI Assistant — Ingestion / ETL Scripts
# Python 3.12-slim + uv (Rust-based package manager, 10-20x faster than pip)
# Запуск через: docker compose --profile ingestion run --rm ingestion ...
# ═══════════════════════════════════════════════════════════════════

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY requirements.txt .
RUN uv pip install -r requirements.txt

# src/ монтируется как volume в docker-compose.yml
COPY src/ ./src/

CMD ["python", "--version"]
