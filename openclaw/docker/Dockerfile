# ═══════════════════════════════════════════════════════════════════
# OpenClaw Gateway — Dockerfile
# Node.js 22 LTS (требование OpenClaw, https://github.com/openclaw/openclaw)
# curl + jq для вызова Python API из SKILL.md; git для npm-зависимостей из GitHub
# ═══════════════════════════════════════════════════════════════════

FROM node:22-slim

ENV HOME=/root \
    GIT_TERMINAL_PROMPT=0

# python3 + build-essential нужны для node-gyp: @discordjs/opus не имеет prebuild под Node 22,
# npm собирает его из исходников.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        jq \
        git \
        python3 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Зависимости openclaw тянутся по git; в образе нет SSH — используем HTTPS через .gitconfig.
RUN mkdir -p /root/.ssh \
 && printf '[url "https://github.com/"]\n\tinsteadOf = ssh://git@github.com/\n\tinsteadOf = git@github.com:\n' >> /root/.gitconfig \
 && npm config set fetch-timeout 300000 \
 && npm config set fetch-retry-mintimeout 20000 \
 && npm config set fetch-retry-maxtimeout 120000 \
 && npm config set fetch-retries 5

# Кэш npm между сборками (BuildKit): повторные сборки и обновления зависимостей быстрее.
ARG OPENCLAW_VERSION=latest
RUN --mount=type=cache,target=/root/.npm \
    npm install -g "openclaw@${OPENCLAW_VERSION}" \
 && openclaw --version

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 18789
ENTRYPOINT ["/entrypoint.sh"]
