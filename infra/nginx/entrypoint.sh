#!/bin/sh
# Генерирует самоподписанный TLS-сертификат при первом запуске.
# Если сертификат уже есть (volume) — пропускает генерацию.

SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/server.crt"
KEY_FILE="$SSL_DIR/server.key"

mkdir -p "$SSL_DIR"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "[nginx] Генерация самоподписанного TLS-сертификата..."
    openssl req -x509 -nodes \
        -days 3650 \
        -newkey rsa:4096 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/C=RU/ST=Russia/L=Moscow/O=Enterprise/OU=IT/CN=enterprise-ai-assistant" \
        -addext "subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:enterprise-ai-assistant" \
        2>/dev/null
    echo "[nginx] Сертификат создан: $CERT_FILE"
    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
else
    echo "[nginx] Сертификат найден, пропускаем генерацию"
fi

exec "$@"
