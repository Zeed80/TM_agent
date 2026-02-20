FROM node:22-alpine

WORKDIR /app

# Устанавливаем зависимости (кешируется отдельно от кода)
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps

# Исходный код монтируется как volume при разработке (hot-reload)
# При production-сборке — копируется ниже:
COPY . .

EXPOSE 3000

# Режим по умолчанию: dev с hot-reload (Vite HMR)
CMD ["npm", "run", "dev"]
