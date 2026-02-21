# ═══════════════════════════════════════════════════════════════════
# OpenClaw Gateway — Dockerfile
# Node.js 22 LTS (требование OpenClaw)
# curl + jq установлены для вызова Python API из SKILL.md скриптов
# ═══════════════════════════════════════════════════════════════════

FROM node:22-slim

# curl — для SKILL.md; jq — JSON; git — npm clone; openssh-client — зависимости openclaw тянутся по ssh:// (libsignal-node и др.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        jq \
        git \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

# npm-зависимости openclaw (libsignal-node и др.) тянутся по ssh://github.com — в образе нет SSH-ключей.
# Перенаправляем git на HTTPS, чтобы клонирование шло без ssh.
RUN git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" && \
    git config --global url."https://github.com/".insteadOf "git@github.com:"

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
