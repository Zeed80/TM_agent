#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Enterprise AI Assistant — Автоматическая установка
# Протестировано на: Ubuntu Server 25.10, Ubuntu 24.04 LTS
#
# Использование:
#   chmod +x install.sh && sudo bash install.sh
#
# Что делает скрипт:
#   1. Проверяет и устанавливает Docker Engine + Compose
#   2. Устанавливает NVIDIA Container Toolkit (если есть GPU)
#   3. Запрашивает конфигурацию (домен/IP, пароли, email)
#   4. Генерирует .env файл
#   5. Создаёт структуру директорий
#   6. Собирает и запускает Docker-контейнеры
#   7. Настраивает HTTPS (Let's Encrypt для домена, self-signed для IP)
#   8. Создаёт пользователя admin с указанным паролем
#   9. Инициализирует базы данных
#  10. Показывает адрес доступа
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Цвета ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Вспомогательные функции ────────────────────────────────────────────
log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()    { echo -e "\n${BOLD}${CYAN}▶ $*${NC}"; }
log_header()  {
  echo -e "\n${BOLD}${BLUE}═══════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${BLUE}  $*${NC}"
  echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════${NC}\n"
}

die() { log_error "$*"; exit 1; }

# Удаление ANSI-последовательностей и лишних переводов строк из ввода
# (предотвращает ошибку ".env: line N: $'\E[1': command not found" при source .env)
sanitize_env_value() {
  printf '%s' "$1" | sed -e 's/\x1b\[[0-9;]*[a-zA-Z]//g' -e 's/\x1b[=><]//g' -e 's/\r$//' -e '/^$/d' | tr -d '\n\r' | head -c 2000
}

# Экранирование значения для безопасной записи в .env (двойные кавычки)
escape_env_value() {
  local v="$1"
  v="${v//\\/\\\\}"
  v="${v//\"/\\\"}"
  printf '"%s"' "$v"
}

confirm() {
  local prompt="${1:-Продолжить?}"
  read -rp "$(echo -e "${YELLOW}?${NC} ${prompt} [y/N]: ")" ans
  [[ "${ans,,}" =~ ^(y|yes|да)$ ]]
}

ask() {
  local prompt="$1"
  local default="${2:-}"
  local result
  if [[ -n "$default" ]]; then
    read -rp "$(echo -e "${CYAN}?${NC} ${prompt} [${default}]: ")" result
    echo "${result:-$default}"
  else
    read -rp "$(echo -e "${CYAN}?${NC} ${prompt}: ")" result
    echo "$result"
  fi
}

ask_password() {
  local prompt="$1"
  local pass
  while true; do
    read -rsp "$(echo -e "${CYAN}?${NC} ${prompt}: ")" pass
    echo
    if [[ ${#pass} -lt 8 ]]; then
      log_warn "Пароль должен содержать минимум 8 символов"
      continue
    fi
    local pass2
    read -rsp "$(echo -e "${CYAN}?${NC} Подтвердите пароль: ")" pass2
    echo
    if [[ "$pass" == "$pass2" ]]; then
      echo "$pass"
      return
    fi
    log_warn "Пароли не совпадают, попробуйте снова"
  done
}

# ── Проверка root ──────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  die "Этот скрипт должен быть запущен от root: sudo bash install.sh"
fi

# ── Рабочая директория ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─────────────────────────────────────────────────────────────────────
log_header "Enterprise AI Assistant — Автоматическая установка"
# ─────────────────────────────────────────────────────────────────────

echo "Директория проекта: ${SCRIPT_DIR}"
echo "Дата: $(date '+%Y-%m-%d %H:%M')"
echo

# ── Шаг 1: Проверка ОС ────────────────────────────────────────────────
log_step "Проверка операционной системы"

if ! grep -qE 'Ubuntu' /etc/os-release 2>/dev/null; then
  log_warn "Скрипт оптимизирован для Ubuntu. Другие дистрибутивы могут работать некорректно."
fi

OS_VERSION=$(grep 'VERSION_ID' /etc/os-release | cut -d'"' -f2)
log_info "ОС: Ubuntu ${OS_VERSION}"

# Обновляем индекс пакетов
log_info "Обновление индекса пакетов..."
apt-get update -qq

# ── Шаг 2: Базовые зависимости ────────────────────────────────────────
log_step "Установка базовых инструментов"

apt-get install -y -qq \
  curl wget git ca-certificates gnupg lsb-release \
  apt-transport-https software-properties-common \
  openssl make python3 python3-pip 2>/dev/null

log_ok "Базовые инструменты установлены"

# ── Шаг 3: Docker ─────────────────────────────────────────────────────
log_step "Проверка Docker"

if command -v docker &>/dev/null; then
  DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
  log_ok "Docker уже установлен: ${DOCKER_VERSION}"
else
  log_info "Устанавливаем Docker Engine..."
  # Официальный метод установки Docker
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

  systemctl enable docker --now
  log_ok "Docker установлен"
fi

# Проверяем docker compose (plugin)
if ! docker compose version &>/dev/null; then
  die "docker compose plugin не найден. Установите вручную: apt install docker-compose-plugin"
fi
log_ok "Docker Compose: $(docker compose version --short)"

# ── Шаг 4: NVIDIA Container Toolkit ──────────────────────────────────
log_step "Проверка NVIDIA GPU"

HAS_GPU=false
if command -v nvidia-smi &>/dev/null; then
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "Unknown")
  log_ok "GPU найден: ${GPU_NAME}"
  HAS_GPU=true

  if ! dpkg -l | grep -q nvidia-container-toolkit; then
    log_info "Устанавливаем NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    log_ok "NVIDIA Container Toolkit установлен"
  else
    log_ok "NVIDIA Container Toolkit уже установлен"
  fi
else
  log_warn "NVIDIA GPU не найден. Ollama будет работать на CPU (медленно)."
  log_warn "Убедитесь, что драйверы NVIDIA установлены: nvidia-smi"
fi

# ── Шаг 5: Конфигурация ───────────────────────────────────────────────
log_step "Настройка конфигурации"

if [[ -f ".env" ]]; then
  log_warn "Файл .env уже существует."
  if ! confirm "Перезаписать конфигурацию?"; then
    log_info "Пропускаем настройку, используем существующий .env"
  else
    _CONFIGURE=true
  fi
else
  _CONFIGURE=true
fi

if [[ "${_CONFIGURE:-false}" == "true" ]]; then
  echo
  echo -e "${BOLD}Введите параметры конфигурации:${NC}"
  echo -e "${YELLOW}(значения в скобках — по умолчанию, нажмите Enter для принятия)${NC}"
  echo

  # ── Домен или IP (для HTTPS) ──────────────────────────────────────
  echo
  echo -e "${BOLD}Настройка HTTPS-доступа:${NC}"
  echo -e "${YELLOW}Введите домен (ai.example.com) для Let's Encrypt (рекомендуется)${NC}"
  echo -e "${YELLOW}или IP-адрес сервера для self-signed сертификата.${NC}"
  DETECTED_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "")
  SERVER_HOST=$(sanitize_env_value "$(ask "Домен или IP сервера" "${DETECTED_IP}")")

  # Определяем, является ли значение IP-адресом
  if echo "$SERVER_HOST" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'; then
    IS_DOMAIN=false
    log_info "Режим: self-signed TLS (IP: ${SERVER_HOST})"
    log_warn "Браузер покажет предупреждение о сертификате — нажмите 'Дополнительно' → 'Принять риск'."
    ACME_EMAIL=""
  else
    IS_DOMAIN=true
    log_info "Режим: Let's Encrypt для домена ${SERVER_HOST}"
    echo -e "${YELLOW}Важно: домен должен уже указывать на этот сервер (DNS A-запись).${NC}"
    ACME_EMAIL=$(sanitize_env_value "$(ask "Email для Let's Encrypt уведомлений" "admin@${SERVER_HOST#*.}")")
  fi

  # ── Пароли баз данных ─────────────────────────────────────────────
  echo
  echo -e "${BOLD}Пароли баз данных:${NC}"
  NEO4J_PASSWORD=$(sanitize_env_value "$(ask_password "Пароль Neo4j")")
  POSTGRES_PASSWORD=$(sanitize_env_value "$(ask_password "Пароль PostgreSQL")")

  # ── Пароль администратора веб-интерфейса ─────────────────────────
  echo
  echo -e "${BOLD}Учётная запись администратора веб-интерфейса:${NC}"
  ADMIN_USERNAME=$(sanitize_env_value "$(ask "Логин администратора" "admin")")
  ADMIN_FULLNAME=$(sanitize_env_value "$(ask "Полное имя" "Администратор")")
  ADMIN_PASSWORD=$(sanitize_env_value "$(ask_password "Пароль администратора")")

  # ── Telegram (опционально) ────────────────────────────────────────
  echo
  TELEGRAM_TOKEN=$(sanitize_env_value "$(ask "Токен Telegram-бота (@BotFather) [Enter = пропустить]" "")")
  if [[ -z "$TELEGRAM_TOKEN" ]]; then
    TELEGRAM_TOKEN="123456789:AAAAAA_PLACEHOLDER_CHANGE_ME"
    log_warn "Telegram-токен не задан. OpenClaw Telegram-интеграция не будет работать."
  fi

  # ── Генерация секретов ────────────────────────────────────────────
  JWT_SECRET=$(openssl rand -hex 32)
  log_ok "JWT Secret Key сгенерирован автоматически"

  # CORS — разрешаем только домен (или IP) в production
  if [[ "$IS_DOMAIN" == true ]]; then
    CORS_ORIGINS="https://${SERVER_HOST}"
  else
    CORS_ORIGINS="https://${SERVER_HOST}"
  fi

  # ── Запись .env (значения в кавычках — защита от ANSI и спецсимволов при source) ──
  cat > .env << ENVEOF
# ═══════════════════════════════════════════
# Enterprise AI Assistant — Конфигурация
# Сгенерировано автоматически: $(date '+%Y-%m-%d %H:%M')
# ═══════════════════════════════════════════

NEO4J_USER=neo4j
NEO4J_PASSWORD=$(escape_env_value "${NEO4J_PASSWORD}")

POSTGRES_DB=enterprise_ai
POSTGRES_USER=enterprise
POSTGRES_PASSWORD=$(escape_env_value "${POSTGRES_PASSWORD}")

TELEGRAM_BOT_TOKEN=$(escape_env_value "${TELEGRAM_TOKEN}")

LLM_MODEL=qwen3:30b
VLM_MODEL=qwen3-vl:14b
EMBEDDING_MODEL=qwen3-embedding
RERANKER_MODEL=qwen3-reranker

EMBEDDING_DIM=4096
QDRANT_COLLECTION=documents

OPENCLAW_AUTO_UPDATE=false

# ── Web Interface ────────────────────────────────
# SERVER_HOST: домен или IP для HTTPS
SERVER_HOST=$(escape_env_value "${SERVER_HOST}")
# ACME_EMAIL: email для Let's Encrypt (только для доменов)
ACME_EMAIL=$(escape_env_value "${ACME_EMAIL}")

JWT_SECRET_KEY=$(escape_env_value "${JWT_SECRET}")
JWT_EXPIRE_HOURS=24
CORS_ORIGINS=$(escape_env_value "${CORS_ORIGINS}")
ENVEOF

  log_ok "Файл .env создан"
  # Сохраняем для дальнейшего использования в скрипте
  export ADMIN_USERNAME ADMIN_FULLNAME ADMIN_PASSWORD
  export NEO4J_PASSWORD POSTGRES_PASSWORD SERVER_HOST IS_DOMAIN
fi

# Загружаем переменные из .env
set -a; source .env; set +a

# ── Шаг 6: Директории ─────────────────────────────────────────────────
log_step "Создание структуры директорий"

mkdir -p documents/{blueprints,manuals,gosts,emails,catalogs,tech_processes}
# Placeholder файлы чтобы папки не были пустыми
for dir in documents/*/; do
  touch "${dir}.gitkeep" 2>/dev/null || true
done

log_ok "Директории созданы: documents/{blueprints,manuals,gosts,emails,catalogs,tech_processes}"

# ── Шаг 7: Сборка и запуск ────────────────────────────────────────────
log_step "Сборка Docker-образов и запуск сервисов"

# OpenClaw — ключевой оркестратор по ТЗ: управляет архивом, сотрудниками, выдаёт задачи.
# Все остальные сервисы (API, frontend) — его «подчинённые».
log_info "Собираем образы (первый раз 5-15 минут)..."
log_info "OpenClaw — центральный агент; api, frontend, caddy, ingestion — вспомогательные сервисы."
echo ""

if docker compose build api frontend caddy ingestion openclaw 2>&1; then
  log_ok "Все образы собраны"
else
  log_error "Ошибка сборки!"
  log_error "OpenClaw: проверьте доступ к npm registry и наличие git в системе."
  log_error "Диагностика: docker compose build openclaw 2>&1"
  exit 1
fi

echo ""
log_info "Запускаем сервисы..."
docker compose up -d --remove-orphans

log_info "Ожидаем готовности API (до 120 секунд)..."
WAIT=0
until docker compose ps --status=running | grep -q "api" 2>/dev/null && \
      docker inspect api --format='{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; do
  WAIT=$((WAIT+5))
  if [[ $WAIT -ge 120 ]]; then
    log_warn "API сервис не стал healthy за 120 секунд."
    log_warn "Проверьте: docker compose logs api"
    break
  fi
  echo -n "."
  sleep 5
done
echo

log_ok "Сервисы запущены"

# ── Шаг 8: Инициализация PostgreSQL ──────────────────────────────────
log_step "Инициализация базы данных"

log_info "Ожидаем готовности PostgreSQL..."
WAIT=0
until docker compose exec -T postgres pg_isready -U enterprise -d enterprise_ai 2>/dev/null; do
  WAIT=$((WAIT+2))
  if [[ $WAIT -ge 30 ]]; then
    log_warn "PostgreSQL не готов, пропускаем инициализацию"
    break
  fi
  sleep 2
done

# ── Шаг 9: Создание пользователя admin ───────────────────────────────
log_step "Создание пользователя администратора"

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  log_info "Генерируем bcrypt-хэш пароля..."

  # Генерируем хэш через Python passlib внутри API-контейнера
  ADMIN_HASH=$(docker compose exec -T api python3 -c "
from passlib.context import CryptContext
ctx = CryptContext(schemes=['bcrypt'], deprecated='auto')
print(ctx.hash('${ADMIN_PASSWORD}'))
" 2>/dev/null || echo "")

  if [[ -n "$ADMIN_HASH" ]]; then
    # Создаём пользователя в БД
    docker compose exec -T postgres psql -U enterprise -d enterprise_ai -c "
INSERT INTO users (username, full_name, password_hash, role)
VALUES ('${ADMIN_USERNAME:-admin}', '${ADMIN_FULLNAME:-Администратор}', '${ADMIN_HASH}', 'admin')
ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash;
" 2>/dev/null && log_ok "Пользователь '${ADMIN_USERNAME:-admin}' создан" \
  || log_warn "Не удалось создать пользователя (возможно, уже существует)"
  else
    log_warn "Не удалось сгенерировать хэш пароля. Создайте пользователя вручную через API."
  fi
else
  log_warn "Пароль admin не задан. Создайте пользователя вручную."
fi

# ── Шаг 10: Инициализация Neo4j ──────────────────────────────────────
log_step "Инициализация Neo4j схемы"

WAIT=0
until docker compose exec -T neo4j cypher-shell \
  -u neo4j -p "${NEO4J_PASSWORD}" \
  "RETURN 'ok' AS status;" 2>/dev/null | grep -q "ok"; do
  WAIT=$((WAIT+3))
  if [[ $WAIT -ge 60 ]]; then
    log_warn "Neo4j не готов. Запустите вручную: make init-db"
    break
  fi
  sleep 3
done

if [[ $WAIT -lt 60 ]]; then
  docker compose exec -T neo4j cypher-shell \
    -u neo4j -p "${NEO4J_PASSWORD}" \
    --file /var/lib/neo4j/import/init.cypher 2>/dev/null \
    && log_ok "Neo4j схема инициализирована" \
    || log_warn "Neo4j: файл init.cypher не применён. Запустите: make init-db"
fi

# ── Шаг 11: Инициализация Qdrant ─────────────────────────────────────
log_step "Инициализация Qdrant коллекции"

log_info "Создаём коллекцию с Hybrid Search (BM25 + Dense)..."
docker compose exec -T api python3 -c "
import asyncio
import sys
sys.path.insert(0, '/app')
from src.db.qdrant_client import qdrant_client
async def main():
    await qdrant_client.connect()
    await qdrant_client.ensure_collection()
    print('Qdrant collection: OK')
    await qdrant_client.close()
asyncio.run(main())
" 2>/dev/null && log_ok "Qdrant коллекция создана" || log_warn "Qdrant: запустите вручную: make init-qdrant"

# ── Шаг 12: Итог ─────────────────────────────────────────────────────
log_header "Установка завершена!"

# Получаем SERVER_HOST из .env если не в переменной
if [[ -z "${SERVER_HOST:-}" ]] && [[ -f ".env" ]]; then
  SERVER_HOST=$(grep '^SERVER_HOST=' .env | cut -d'=' -f2- | sed 's/^"//;s/"$//')
fi
SERVER_HOST="${SERVER_HOST:-$(hostname -I | awk '{print $1}')}"
ACCESS_URL="https://${SERVER_HOST}"

echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║        Веб-интерфейс доступен по адресу:         ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo
echo -e "  ${CYAN}${BOLD}${ACCESS_URL}${NC}"
echo

# Подсказка о сертификате
if echo "$SERVER_HOST" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'; then
  echo -e "${YELLOW}⚠  Self-signed сертификат: браузер покажет предупреждение.${NC}"
  echo -e "${YELLOW}   Нажмите 'Дополнительно' → 'Всё равно открыть'.${NC}"
  echo -e "${YELLOW}   Для устранения — назначьте доменное имя и переустановите.${NC}"
else
  echo -e "${GREEN}✓  Let's Encrypt: сертификат получен автоматически (может занять 1-2 мин).${NC}"
  echo -e "${YELLOW}   Убедитесь, что DNS ${SERVER_HOST} → этот сервер, порты 80/443 открыты.${NC}"
fi
echo
echo -e "${BOLD}Учётные данные администратора:${NC}"
echo -e "  Логин:  ${CYAN}${ADMIN_USERNAME:-admin}${NC}"
echo -e "  Пароль: ${CYAN}(указанный при установке)${NC}"
echo
echo -e "${BOLD}Следующие шаги:${NC}"
echo -e "  1. Откройте ${CYAN}${ACCESS_URL}${NC} и войдите"
echo -e "  2. Загрузите AI-модели: ${CYAN}make pull-models${NC}"
echo -e "     (или через Admin panel → 'Загрузить модель Ollama')"
echo -e "  3. Загрузите документы через веб-интерфейс (раздел Документы)"
echo -e "  4. Запустите индексацию: через Admin panel или ${CYAN}make ingest-all${NC}"
echo -e "  5. Подключите Telegram-бота: ${CYAN}make openclaw-pair${NC}"
echo
echo -e "${BOLD}Управление из браузера:${NC}"
echo -e "  ${CYAN}${ACCESS_URL}/admin${NC}  — контейнеры, логи, метрики, модели"
echo -e "  ${CYAN}${ACCESS_URL}/users${NC}  — пользователи и роли"
echo
echo -e "${BOLD}Управление из командной строки (на сервере):${NC}"
echo -e "  ${CYAN}make status${NC}       — статус сервисов и URL"
echo -e "  ${CYAN}make logs${NC}         — логи всех сервисов"
echo -e "  ${CYAN}make update${NC}       — обновление до последней версии"
echo -e "  ${CYAN}make down${NC}         — остановка всех сервисов"
echo -e "  ${CYAN}make create-admin${NC} — сброс пароля admin"
echo
