#!/bin/sh
# Генерирует Caddyfile на основе переменных окружения и запускает Caddy.
#
# Логика выбора TLS:
#   SERVER_HOST = домен (пр. ai.example.com)  → Let's Encrypt (ACME)
#   SERVER_HOST = IP или localhost             → tls internal (self-signed)
#
# Env vars:
#   SERVER_HOST   — домен или IP (обязательно)
#   ACME_EMAIL    — email для Let's Encrypt (только для доменов)
#   CADDY_TLS     — принудительно: "internal" = самоподписанный (для домена тоже),
#                   не задан = авто (IP/localhost → internal, домен → Let's Encrypt)

set -e

SERVER_HOST="${SERVER_HOST:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-}"
CADDY_TLS="${CADDY_TLS:-}"

# Определяем, является ли SERVER_HOST IP-адресом или localhost
is_ip_or_localhost() {
  echo "$1" | grep -qE '^(localhost|127\.|192\.|10\.|172\.|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})$'
}

# Проверяем наличие уже полученного сертификата в volume (переживает teardown)
HAS_EXISTING_CERT=0
if [ -d /data/caddy ] && [ -n "$(ls -A /data/caddy/certificates 2>/dev/null)" ]; then
  HAS_EXISTING_CERT=1
fi

# Определяем TLS-директиву
if [ "$CADDY_TLS" = "internal" ]; then
  TLS_BLOCK="tls internal"
  echo "[Caddy] Режим: self-signed TLS (принудительно CADDY_TLS=internal для ${SERVER_HOST})"
elif is_ip_or_localhost "$SERVER_HOST"; then
  TLS_BLOCK="tls internal"
  echo "[Caddy] Режим: self-signed TLS (IP/localhost: ${SERVER_HOST})"
else
  TLS_BLOCK=""
  if [ "$HAS_EXISTING_CERT" = 1 ]; then
    echo "[Caddy] Режим: домен ${SERVER_HOST}; обнаружен существующий сертификат в /data/caddy — используем его"
  else
    echo "[Caddy] Режим: Let's Encrypt для домена ${SERVER_HOST}"
  fi
fi

# Формируем глобальный блок
if [ -n "$ACME_EMAIL" ]; then
  GLOBAL_BLOCK="{
  email ${ACME_EMAIL}
  admin off
}"
else
  GLOBAL_BLOCK="{
  admin off
}"
fi

# Генерируем Caddyfile
cat > /etc/caddy/Caddyfile << CADDYEOF
${GLOBAL_BLOCK}

${SERVER_HOST} {
  ${TLS_BLOCK}

  encode gzip zstd

  # Блокируем прямой доступ к внутренним skill endpoints
  respond /skills/* 403

  # FastAPI: Web API (auth, chat, files, admin)
  reverse_proxy /api/* api:8000 {
    header_up X-Real-IP        {remote_host}
    header_up X-Forwarded-For  {remote_host}
    header_up X-Forwarded-Proto {scheme}
    transport http {
      response_header_timeout 3m
    }
  }

  # Swagger UI (для разработки)
  reverse_proxy /docs     api:8000
  reverse_proxy /redoc    api:8000
  reverse_proxy /openapi.json api:8000

  # React SPA — включая Vite HMR WebSocket
  reverse_proxy /* frontend:3000 {
    header_up Upgrade    {http.request.header.Upgrade}
    header_up Connection {http.request.header.Connection}
  }
}
CADDYEOF

echo "[Caddy] Caddyfile сгенерирован:"
cat /etc/caddy/Caddyfile

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
