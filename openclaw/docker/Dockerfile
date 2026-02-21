# ═══════════════════════════════════════════════════════════════════
# OpenClaw Gateway — Dockerfile
# Node.js 22 LTS (требование OpenClaw, https://github.com/openclaw/openclaw)
# curl + jq для вызова Python API из SKILL.md; git для npm-зависимостей из GitHub
# ═══════════════════════════════════════════════════════════════════

FROM node:22-slim

ENV HOME=/root \
    GIT_TERMINAL_PROMPT=0

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        jq \
        git \
    && rm -rf /var/lib/apt/lists/*

# Зависимости openclaw (@whiskeysockets/baileys → libsignal-node) тянутся по ssh:// —
# в образе нет SSH-ключей. Записываем .gitconfig вручную и ставим openclaw в ОДНОМ RUN,
# чтобы git точно использовал HTTPS при вызове из npm.
RUN mkdir -p /root/.ssh \
 && printf '[url "https://github.com/"]\n\tinsteadOf = ssh://git@github.com/\n\tinsteadOf = git@github.com:\n' >> /root/.gitconfig \
 && (git config --global --list | grep -E 'url\.|insteadOf' || true) \
 && unset GIT_SSH_COMMAND \
 && npm config set fetch-timeout 300000 \
 && npm config set fetch-retry-mintimeout 20000 \
 && npm config set fetch-retry-maxtimeout 120000 \
 && npm config set fetch-retries 5 \
 && npm install -g openclaw@latest \
 && openclaw --version

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 18789
ENTRYPOINT ["/entrypoint.sh"]
