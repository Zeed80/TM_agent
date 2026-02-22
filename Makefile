SHELL := /bin/bash

# ═══════════════════════════════════════════════
# Enterprise AI Assistant — Makefile
# Использование: make <target>
# ═══════════════════════════════════════════════

.PHONY: help up down restart ps logs logs-all logs-caddy logs-api logs-gpu \
        update update-openclaw update-api update-frontend openclaw-pair \
        restart-caddy check-web \
        init-db init-pg init-qdrant pull-models \
        ingest-excel ingest-pdf ingest-blueprints ingest-techprocess ingest-all \
        shell-api shell-neo4j shell-pg shell-qdrant \
        create-admin status \
        backup-pg restore-pg clean teardown

# Загружаем переменные из .env для использования в make-командах
-include .env
export

# ──────────────────────────────────────────────
# Базовые операции
# ──────────────────────────────────────────────

up: ## Запустить все сервисы
	docker compose up -d
	@echo ""
	@echo "✓ Сервисы запущены. Статус: make ps"
	@echo "✓ Логи API:       make logs"
	@echo "✓ После первого запуска выполни: make pull-models && make init-db"

down: ## Остановить все сервисы (данные сохраняются в volumes)
	docker compose down

restart: ## Перезапустить все сервисы
	docker compose restart

ps: ## Показать статус контейнеров
	docker compose ps

logs: ## Следить за логами api + openclaw
	docker compose logs -f api openclaw

logs-all: ## Следить за логами всех сервисов
	docker compose logs -f

logs-gpu: ## Логи Ollama GPU (LLM/VLM)
	docker compose logs -f ollama-gpu

logs-api: ## Логи только Python API
	docker compose logs -f api

# ──────────────────────────────────────────────
# Обновление сервисов (без потери данных)
# ──────────────────────────────────────────────

update: ## Пересобрать и перезапустить все сервисы (данные в volumes не трогаются)
	docker compose build openclaw api frontend caddy ingestion
	docker compose up -d openclaw api frontend caddy
	@echo "✓ Обновление завершено"

update-openclaw: ## Обновить только OpenClaw контейнер
	docker compose build openclaw
	docker compose up -d openclaw

openclaw-pair: ## Подсказка: как подключить Telegram-бота к OpenClaw
	@echo "OpenClaw Telegram: задайте TELEGRAM_BOT_TOKEN в .env и перезапустите openclaw (docker compose restart openclaw)."
	@echo "Затем в Telegram найдите бота по имени и отправьте /start или команду из документации OpenClaw (dmPolicy: pairing)."

update-api: ## Пересобрать зависимости API (requirements.txt изменился)
	docker compose build api
	docker compose up -d api

update-frontend: ## Пересобрать фронтенд (package.json изменился)
	docker compose build frontend
	docker compose up -d frontend

status: ## Статус всех контейнеров + URL доступа
	@docker compose ps
	@echo ""
	@SERVER=$$(grep '^SERVER_HOST=' .env 2>/dev/null | cut -d'=' -f2 || hostname -I | awk '{print $$1}'); \
	  echo "  Web UI:     https://$$SERVER"; \
	  echo "  Admin:      https://$$SERVER/admin"; \
	  echo "  API Docs:   https://$$SERVER/docs"

logs-caddy: ## Логи Caddy (HTTPS / Let's Encrypt)
	docker compose logs -f caddy

restart-caddy: ## Перезапустить Caddy (обновить конфиг)
	docker compose restart caddy

check-web: ## Диагностика: почему не открывается веб-интерфейс
	@echo "=== Контейнеры (caddy, frontend, api) ==="
	@docker compose ps
	@echo ""
	@echo "=== SERVER_HOST из .env ==="
	@grep '^SERVER_HOST=' .env 2>/dev/null || echo "  .env не найден или SERVER_HOST не задан"
	@echo ""
	@echo "=== Ответ Caddy по SERVER_HOST (ожидается 200) ==="
	@H=$$(grep '^SERVER_HOST=' .env 2>/dev/null | cut -d= -f2- | sed 's/^"//;s/"$$//'); \
	  if [ -n "$$H" ]; then \
	    code=$$(curl -k -s -o /dev/null -w "%{http_code}" "https://$$H/" 2>/dev/null || echo "err"); \
	    echo "  https://$$H/ -> HTTP $$code"; \
	    if [ "$$code" != "200" ] && [ "$$code" != "304" ]; then \
	      echo "  Если 000/err — домен недоступен с этой машины. Попробуйте по IP: https://<IP-сервера>"; \
	      echo "  При лимите Let's Encrypt (429): в .env добавьте CADDY_TLS=internal и make restart-caddy"; \
	    fi; \
	  else echo "  Задайте SERVER_HOST в .env"; fi
	@echo ""
	@echo "=== Ответ Caddy по 127.0.0.1 (локальный вход по IP) ==="
	@code=$$(curl -k -s -o /dev/null -w "%{http_code}" "https://127.0.0.1/" 2>/dev/null || echo "err"); \
	  echo "  https://127.0.0.1/ -> HTTP $$code"; \
	  if [ "$$code" = "200" ] || [ "$$code" = "304" ]; then echo "  OK: заходите по https://127.0.0.1 или https://<IP-сервера> (примите самоподписанный сертификат)"; fi
	@echo ""
	@echo "=== Доступность frontend:3000 из контейнера caddy ==="
	@docker compose exec -T caddy wget -qO- --timeout=3 http://frontend:3000/ 2>/dev/null | head -c 80 && echo " ... OK" || echo "  Таймаут или ошибка"
	@echo ""
	@echo "=== Последние логи Caddy ==="
	@docker compose logs caddy --tail 12
	@echo ""
	@echo "Подробнее: docs/TROUBLESHOOTING_WEB.md"

create-admin: ## Создать/обновить пользователя admin (запрашивает пароль)
	@read -sp "Пароль для admin: " PASS && echo "" && \
	HASH=$$(docker compose exec -T api python3 -c \
	  "import bcrypt,sys; p=sys.argv[1].encode('utf-8')[:72]; print(bcrypt.hashpw(p,bcrypt.gensalt()).decode())" "$$PASS") && \
	docker compose exec -T postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" -c \
	  "INSERT INTO users (username, full_name, password_hash, role) \
	   VALUES ('admin','Администратор','$$HASH','admin') \
	   ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash;" && \
	echo "✓ Пользователь admin создан/обновлён"

# ──────────────────────────────────────────────
# Инициализация (выполняется один раз)
# ──────────────────────────────────────────────

init-db: ## Инициализировать схему Neo4j (constraints + indexes)
	@echo "→ Инициализация схемы Neo4j..."
	@docker compose exec -T neo4j cypher-shell \
		-u "$(NEO4J_USER)" \
		-p "$(NEO4J_PASSWORD)" \
		--non-interactive \
		-f /var/lib/neo4j/import/init.cypher
	@echo "✓ Схема Neo4j инициализирована"

init-pg: ## Применить миграции к существующей БД (02–05). При новой установке не нужен: скрипты из docker-entrypoint-initdb.d выполняются при первом запуске контейнера.
	@echo "→ Применение схемы users, chat_sessions, chat_messages, uploaded_files..."
	@docker compose exec -T postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" < infra/postgres/02_users.sql
	@echo "→ Применение схемы model_providers, model_assignments..."
	@docker compose exec -T postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" < infra/postgres/03_model_providers.sql
	@echo "→ Колонка encrypted_api_key для ключей провайдеров..."
	@docker compose exec -T postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" < infra/postgres/04_provider_api_keys.sql
	@echo "→ Таблица app_settings для настроек из Web UI..."
	@docker compose exec -T postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" < infra/postgres/05_app_settings.sql
	@echo "✓ Схема PostgreSQL применена. Создай admin: make create-admin"

init-qdrant: ## Создать коллекцию Qdrant с Sparse + Dense векторами
	@echo "→ Инициализация коллекции Qdrant..."
	@docker compose run --rm ingestion python -m src.setup_qdrant
	@echo "✓ Коллекция Qdrant создана"

pull-models: ## Загрузить все Ollama-модели (требует интернета, ~40GB)
	@echo "→ Загрузка LLM qwen3:30b на GPU (~18GB)..."
	docker compose exec ollama-gpu ollama pull $(LLM_MODEL)
	@echo "→ Загрузка VLM qwen3-vl:14b на GPU storage (~9GB)..."
	docker compose exec ollama-gpu ollama pull $(VLM_MODEL)
	@echo "→ Загрузка Embedding-модели на CPU..."
	docker compose exec ollama-cpu ollama pull $(EMBEDDING_MODEL)
	@echo "→ Загрузка Reranker-модели на CPU..."
	docker compose exec ollama-cpu ollama pull $(RERANKER_MODEL)
	@echo "✓ Все модели загружены"
	@echo ""
	@echo "Проверь размерность эмбеддингов:"
	@echo "  docker compose exec ollama-cpu ollama show $(EMBEDDING_MODEL) --verbose"
	@echo "Затем обнови EMBEDDING_DIM в .env и перезапусти: make update-api"

# ──────────────────────────────────────────────
# ETL — Загрузка данных
# ──────────────────────────────────────────────

ingest-excel: ## Загрузить Excel/CSV каталоги в PostgreSQL
	docker compose --profile ingestion run --rm ingestion \
		python -m src.excel_ingestion

ingest-pdf: ## Загрузить PDF/DOCX/EML документы в Qdrant
	docker compose --profile ingestion run --rm ingestion \
		python -m src.pdf_text_ingestion

ingest-blueprints: ## Загрузить чертежи (VLM → Neo4j + Qdrant)
	docker compose --profile ingestion run --rm ingestion \
		python -m src.blueprint_ingestion

ingest-techprocess: ## Загрузить техпроцессы в граф Neo4j
	docker compose --profile ingestion run --rm ingestion \
		python -m src.tech_process_ingestion

ingest-all: ## Запустить все ETL-пайплайны последовательно
	$(MAKE) ingest-excel
	$(MAKE) ingest-pdf
	$(MAKE) ingest-blueprints
	$(MAKE) ingest-techprocess
	@echo "✓ Полная загрузка данных завершена"

# ──────────────────────────────────────────────
# Интерактивные оболочки
# ──────────────────────────────────────────────

shell-api: ## Bash в контейнере API
	docker compose exec api bash

shell-neo4j: ## Cypher Shell (Neo4j)
	docker compose exec neo4j cypher-shell -u "$(NEO4J_USER)" -p "$(NEO4J_PASSWORD)"

shell-pg: ## psql (PostgreSQL)
	docker compose exec postgres psql -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)"

shell-qdrant: ## Проверить коллекции Qdrant через API
	@curl -s http://localhost:6333/collections | python3 -m json.tool

shell-ollama-gpu: ## Интерактивный Ollama GPU
	docker compose exec ollama-gpu ollama list

shell-ollama-cpu: ## Список моделей Ollama CPU
	docker compose exec ollama-cpu ollama list

# ──────────────────────────────────────────────
# Резервное копирование
# ──────────────────────────────────────────────

backup-pg: ## Создать дамп PostgreSQL в ./backups/
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S) && \
	docker compose exec -T postgres pg_dump \
		-U "$(POSTGRES_USER)" "$(POSTGRES_DB)" \
		| gzip > backups/pg_backup_$$TIMESTAMP.sql.gz && \
	echo "✓ Дамп создан: backups/pg_backup_$$TIMESTAMP.sql.gz"

restore-pg: ## Восстановить PostgreSQL из файла: make restore-pg FILE=backups/pg_backup_xxx.sql.gz
	@[ -n "$(FILE)" ] || (echo "Укажи файл: make restore-pg FILE=backups/file.sql.gz" && exit 1)
	@echo "→ Восстановление из $(FILE)..."
	gunzip -c "$(FILE)" | docker compose exec -T postgres psql \
		-U "$(POSTGRES_USER)" "$(POSTGRES_DB)"
	@echo "✓ Восстановление завершено"

# ──────────────────────────────────────────────
# Очистка
# ──────────────────────────────────────────────

clean: ## Остановить контейнеры и удалить ВСЕ данные (volumes). Необратимо!
	@echo "ВНИМАНИЕ: Это удалит все данные (Neo4j, PostgreSQL, Qdrant, модели Ollama)!"
	@read -p "Ты уверен? Напечатай 'yes': " confirm && [ "$$confirm" = "yes" ] || exit 1
	docker compose down -v --remove-orphans
	@echo "✓ Контейнеры и volumes удалены"

# Полное удаление: контейнеры, сети, volumes + образы проекта.
# Сертификаты Caddy хранятся на хосте (CADDY_DATA_PATH) и не удаляются.
teardown: ## Полная очистка: контейнеры, volumes, образы проекта. Чистый старт.
	@echo "ВНИМАНИЕ: Будет удалено:"
	@echo "  — все контейнеры и сети проекта"
	@echo "  — все volumes проекта"
	@echo "  — образы tm_agent-* (api, frontend, caddy, openclaw, ingestion)"
	@echo "  — Сертификаты Caddy на хосте (CADDY_DATA_PATH) не удаляются"
	@echo "После этого: make up и при необходимости docker compose build"
	@read -p "Продолжить? Напечатай 'yes': " confirm && [ "$$confirm" = "yes" ] || exit 1
	docker compose down -v --rmi local --remove-orphans
	@echo "✓ Teardown завершён. Для запуска: make up"

# ──────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────

help: ## Показать эту справку
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
