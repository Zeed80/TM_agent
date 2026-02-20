# ═══════════════════════════════════════════════════════════════════
# Enterprise AI Assistant — Python FastAPI
# Python 3.12-slim
# src/ монтируется как volume в docker-compose.yml →
# uvicorn --reload обеспечивает горячую перезагрузку без rebuild
# ═══════════════════════════════════════════════════════════════════

FROM python:3.12-slim

WORKDIR /app

# Системные зависимости:
# - curl: health check
# - libpq-dev: asyncpg нативные расширения
# - gcc: компиляция нативных модулей (fastembed, asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# Сначала копируем только requirements.txt — кэш слой.
# Если requirements.txt не изменился, pip install не перезапускается.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем src/ в образ (будет переопределён volume mount в dev-режиме)
COPY src/ ./src/

EXPOSE 8000

# --reload-dir гарантирует, что uvicorn следит именно за /app/src,
# даже если volume монтируется позже
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--reload", \
     "--reload-dir", "/app/src"]
