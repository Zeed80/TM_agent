#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
# OpenClaw Entrypoint
# OPENCLAW_AUTO_UPDATE=true — обновление до latest перед запуском.
# Конфиг: /opt/openclaw-config (bind ./openclaw) → копируем openclaw.json
# в /root/.openclaw/, чтобы не монтировать файл впрямую (на хосте его может не быть → EISDIR).
# ═══════════════════════════════════════════════════════════════════

set -e

if [ "${OPENCLAW_AUTO_UPDATE:-false}" = "true" ]; then
    echo "[openclaw] Auto-update enabled — installing latest version..."
    npm install -g openclaw@latest --quiet
    echo "[openclaw] Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
else
    echo "[openclaw] Auto-update disabled. Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
fi

mkdir -p /root/.openclaw
CONFIG_DEST="/root/.openclaw/openclaw.json"
if [ -f /opt/openclaw-config/openclaw.json ]; then
    echo "[openclaw] Using config from /opt/openclaw-config/openclaw.json"
    cp /opt/openclaw-config/openclaw.json "$CONFIG_DEST"
else
    echo "[openclaw] No openclaw.json on host, using default config (OpenClaw 2026 schema)"
    cat > "$CONFIG_DEST" << 'EOF'
{"gateway":{"mode":"local","port":18789,"bind":"lan"},"agents":{"defaults":{"workspace":"/root/.openclaw/workspace"}},"channels":{"telegram":{"enabled":true,"botToken":"","dmPolicy":"pairing"}}}
EOF
fi

echo "[openclaw] Starting Gateway on port 18789..."
exec openclaw gateway --port 18789
