FROM nginx:1.27-alpine

# Инструменты для генерации сертификата
RUN apk add --no-cache openssl

# Конфигурация nginx
COPY nginx.conf /etc/nginx/nginx.conf

# Скрипт точки входа: генерирует самоподписанный cert при первом запуске
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
