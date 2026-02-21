# ═══════════════════════════════════════════════════════════════════
# OpenClaw Gateway — Dockerfile
# Node.js 22 LTS (требование OpenClaw)
# curl + jq установлены для вызова Python API из SKILL.md скриптов
# ═══════════════════════════════════════════════════════════════════

FROM node:22-slim

# curl — для curl-вызовов в SKILL.md; jq — парсинг JSON; git — npm требует для некоторых зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        jq \
        git \
    && rm -rf /var/lib/apt/lists/*

# Установить OpenClaw глобально (ключевой оркестратор по ТЗ)
RUN npm config set fetch-timeout 300000 \
 && npm config set fetch-retry-mintimeout 20000 \
 && npm config set fetch-retry-maxtimeout 120000 \
 && npm config set fetch-retries 5 \
 && npm install -g openclaw@latest \
 && openclaw --version

# Скопировать entrypoint-скрипт
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 18789

ENTRYPOINT ["/entrypoint.sh"]
