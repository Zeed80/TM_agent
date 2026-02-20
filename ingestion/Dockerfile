# ═══════════════════════════════════════════════════════════════════
# Enterprise AI Assistant — Ingestion / ETL Scripts
# Python 3.12-slim
# Запуск через: docker compose --profile ingestion run --rm ingestion ...
# ═══════════════════════════════════════════════════════════════════

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# src/ монтируется как volume в docker-compose.yml
COPY src/ ./src/

# По умолчанию контейнер не запускает ничего — управляется через make ingest-*
CMD ["python", "--version"]
