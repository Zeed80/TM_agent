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
    # Модель: приоритет — из API (настройки в Web UI), иначе из env
    OC_MODEL="${LLM_MODEL:-qwen3:30b}"
    if _api_model=$(curl -sf "http://api:8000/api/v1/settings/public" 2>/dev/null | jq -r '.llm_model // empty'); then
        if [ -n "$_api_model" ]; then
            OC_MODEL="$_api_model"
            echo "[openclaw] LLM model from API (Web UI): ollama/${OC_MODEL}"
        else
            echo "[openclaw] LLM model from env: ollama/${OC_MODEL}"
        fi
    else
        echo "[openclaw] LLM model from env: ollama/${OC_MODEL}"
    fi
    # Формируем JSON: gateway, agents (workspace + model), channels, models.providers.ollama
    _gateway='{"mode":"local","port":18789,"bind":"lan"}'
    _agents_workspace='"/root/.openclaw/workspace"'
    _model_primary="ollama/${OC_MODEL}"
    _ollama_provider="{\"baseUrl\":\"http://ollama-gpu:11434\",\"apiKey\":\"ollama-local\",\"api\":\"ollama\",\"models\":[{\"id\":\"${OC_MODEL}\",\"name\":\"LLM ${OC_MODEL}\",\"reasoning\":false,\"input\":[\"text\"],\"cost\":{\"input\":0,\"output\":0,\"cacheRead\":0,\"cacheWrite\":0},\"contextWindow\":32768,\"maxTokens\":32768}]}"
    if [ -n "${TELEGRAM_BOT_TOKEN}" ]; then
        echo "[openclaw] TELEGRAM_BOT_TOKEN set — enabling Telegram (token from env)"
        _channels="{\"telegram\":{\"enabled\":true,\"botToken\":\"${TELEGRAM_BOT_TOKEN}\",\"dmPolicy\":\"pairing\"}}"
    else
        echo "[openclaw] TELEGRAM_BOT_TOKEN not set — Telegram disabled. Set in .env and restart to enable."
        _channels='{"telegram":{"enabled":false}}'
    fi
    # Собираем итоговый JSON (одна строка без переносов)
    printf '%s\n' "{\"gateway\":${_gateway},\"agents\":{\"defaults\":{\"workspace\":${_agents_workspace},\"model\":{\"primary\":\"${_model_primary}\"}}},\"channels\":${_channels},\"models\":{\"providers\":{\"ollama\":${_ollama_provider}}}}" > "$CONFIG_DEST"
fi

# Штатная настройка OpenClaw после развёртывания: нормализация конфига, миграции и генерация
# ключа доступа (gateway.auth.token) для Control UI. Без токена вход в /openclaw/__openclaw__/canvas/ невозможен.
echo "[openclaw] Running doctor (fix + generate gateway token)..."
if openclaw doctor --fix --non-interactive --generate-gateway-token 2>/dev/null; then
    echo "[openclaw] Doctor completed."
else
    # Если флаг --generate-gateway-token не поддерживается в данной версии — gateway сгенерирует токен при старте
    openclaw doctor --fix --non-interactive 2>/dev/null || true
fi

# Сохраняем токен gateway в общий volume, чтобы API мог отдать его админу (вход в Control UI)
SETUP_DIR="/run/openclaw-setup"
if [ -d "$SETUP_DIR" ]; then
  _token=""
  if _token=$(openclaw config get gateway.auth.token 2>/dev/null); then
    printf '%s' "$_token" | tr -d '\n' > "$SETUP_DIR/gateway.token"
    echo "[openclaw] Токен для Control UI записан в $SETUP_DIR (доступен в Настройки → OpenClaw)."
  fi
fi

echo "[openclaw] Starting Gateway on port 18789..."
echo "[openclaw] Для входа откройте /openclaw/__openclaw__/canvas/ и введите токен из Настройки → OpenClaw (кнопка «Показать токен»)."
exec openclaw gateway --port 18789
