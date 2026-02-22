#!/usr/bin/env bash
# Если Caddy не смог получить сертификат (например Let's Encrypt 429),
# добавляет в .env CADDY_TLS=internal и перезапускает Caddy.
# Запускать с корня проекта; после make up вызывается автоматически с задержкой.

set -e

cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env}"

# Ждём, пока Caddy появится в ps (до 30 сек)
for i in {1..30}; do
  if docker compose ps caddy 2>/dev/null | grep -qE 'Up|running'; then
    break
  fi
  [[ $i -eq 30 ]] && { echo "[caddy-fallback] Caddy не запущен, пропуск."; exit 0; }
  sleep 1
done

# Даём Caddy время попытаться получить сертификат (ACME)
sleep "${CADDY_FALLBACK_DELAY:-95}"

LOGS=$(docker compose logs caddy --tail 400 2>/dev/null || true)
if ! echo "$LOGS" | grep -qE '429|could not get certificate|rate limit|rateLimited|too many certificates'; then
  exit 0
fi

if grep -qE '^CADDY_TLS=internal' "$ENV_FILE" 2>/dev/null; then
  echo "[caddy-fallback] CADDY_TLS=internal уже задан в .env"
  exit 0
fi

echo "[caddy-fallback] Обнаружена ошибка получения сертификата; добавляю CADDY_TLS=internal в .env и перезапускаю Caddy"
echo 'CADDY_TLS=internal' >> "$ENV_FILE"
docker compose up -d caddy
echo "[caddy-fallback] Готово. Сайт должен открываться по https (примите самоподписанный сертификат в браузере)."
