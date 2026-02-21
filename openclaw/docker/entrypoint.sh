#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
# OpenClaw Entrypoint
# Если OPENCLAW_AUTO_UPDATE=true — обновляет OpenClaw до latest
# перед запуском Gateway.
# Если на хосте нет openclaw.json, Docker создаёт каталог вместо файла (EISDIR) —
# заменяем каталог на конфиг по умолчанию.
# ═══════════════════════════════════════════════════════════════════

set -e

if [ "${OPENCLAW_AUTO_UPDATE:-false}" = "true" ]; then
    echo "[openclaw] Auto-update enabled — installing latest version..."
    npm install -g openclaw@latest --quiet
    echo "[openclaw] Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
else
    echo "[openclaw] Auto-update disabled. Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
fi

CONFIG_PATH="/root/.openclaw/openclaw.json"
if [ -d "$CONFIG_PATH" ]; then
    echo "[openclaw] openclaw.json was a directory (bind mount without host file), replacing with default config"
    rm -rf "$CONFIG_PATH"
fi
if [ ! -f "$CONFIG_PATH" ]; then
    echo "[openclaw] Creating default openclaw.json"
    mkdir -p /root/.openclaw
    cat > "$CONFIG_PATH" << 'EOF'
{"gateway":{"port":18789,"bind":"all"},"agents":{"defaults":{"workspace":"/root/.openclaw/workspace"}},"models":{"ollama":{"baseUrl":"http://ollama-gpu:11434"}},"channels":{"telegram":{"botToken":"","dmPolicy":"pairing"}},"commands":{"nativeSkills":"auto"}}
EOF
fi

echo "[openclaw] Starting Gateway on port 18789..."
exec openclaw gateway --port 18789
