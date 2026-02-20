FROM caddy:2.9-alpine

# Entrypoint генерирует Caddyfile из переменных окружения при старте
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
