#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
# OpenClaw Entrypoint
# Если OPENCLAW_AUTO_UPDATE=true — обновляет OpenClaw до latest
# перед запуском Gateway.
# Управляется через .env: OPENCLAW_AUTO_UPDATE=true|false
# ═══════════════════════════════════════════════════════════════════

set -e

if [ "${OPENCLAW_AUTO_UPDATE:-false}" = "true" ]; then
    echo "[openclaw] Auto-update enabled — installing latest version..."
    npm install -g openclaw@latest --quiet
    echo "[openclaw] Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
else
    echo "[openclaw] Auto-update disabled. Version: $(openclaw --version 2>/dev/null || echo 'unknown')"
fi

echo "[openclaw] Starting Gateway on port 18789..."
exec openclaw gateway --port 18789
