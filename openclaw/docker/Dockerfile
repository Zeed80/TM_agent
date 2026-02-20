# ═══════════════════════════════════════════════════════════════════
# OpenClaw Gateway — Dockerfile
# Node.js 22 LTS (требование OpenClaw)
# curl + jq установлены для вызова Python API из SKILL.md скриптов
# ═══════════════════════════════════════════════════════════════════

FROM node:22-slim

# Установить curl (для curl-вызовов в SKILL.md) и jq (для парсинга JSON)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        jq \
    && rm -rf /var/lib/apt/lists/*

# Установить OpenClaw глобально
RUN npm install -g openclaw@latest

# Скопировать entrypoint-скрипт
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 18789

ENTRYPOINT ["/entrypoint.sh"]
