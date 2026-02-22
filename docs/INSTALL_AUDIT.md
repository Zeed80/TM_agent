# Аудит установки через install.sh

**Дата:** 22.02.2025  
**Цель:** Полная проверка скрипта автоматической установки `install.sh`: соответствие docker-compose, .env, инициализации БД, безопасности и документации.

---

## 1. Обзор скрипта

| Параметр | Значение |
|----------|----------|
| Файл | `install.sh` (корень проекта) |
| Запуск | `sudo bash install.sh` или `sudo bash install.sh --teardown` |
| ОС | Ubuntu (рекомендуется 24.04 LTS, 25.10) |
| Требования | root, интернет, при наличии GPU — драйверы NVIDIA |

**Последовательность шагов (по скрипту):**

1. Проверка ОС и обновление индекса пакетов  
2. Установка базовых инструментов (curl, wget, git, openssl, make, python3)  
3. Установка/проверка Docker Engine и docker compose (plugin)  
4. Установка NVIDIA Container Toolkit (если есть nvidia-smi)  
5. Конфигурация: запрос домена/IP, паролей БД, admin, Telegram; генерация .env  
6. Создание директорий `documents/{blueprints,manuals,gosts,emails,catalogs,tech_processes}`  
7. Сборка образов (api, frontend, caddy, ingestion, openclaw) и `docker compose up -d`  
8. Ожидание готовности PostgreSQL  
9. Создание пользователя admin в PostgreSQL (bcrypt-хэш)  
10. Инициализация Neo4j (init.cypher)  
11. Инициализация Qdrant (коллекция через API)  
12. Вывод URL доступа и следующих шагов  

---

## 2. Соответствие инфраструктуре

### 2.1 Docker Compose

- **Ollama GPU/CPU:** в compose используются образы `ollama/ollama:latest` (не сборка). Скрипт их не собирает — при `docker compose up -d` образы подтягиваются автоматически. ✅  
- **Сборка:** скрипт собирает только `api frontend caddy ingestion openclaw`. Остальные сервисы (postgres, neo4j, qdrant, ollama-gpu, ollama-cpu) — образы из реестра. ✅  
- **Запуск:** `docker compose up -d --remove-orphans` поднимает все сервисы без профилей. ✅  
- **Зависимости:** API зависит от postgres, neo4j, qdrant, ollama-gpu, ollama-cpu (condition: service_healthy). Ожидание 120 с для API healthy перед созданием admin — корректно. ✅  

### 2.2 Переменные .env

Скрипт записывает в .env:

| Переменная | Источник в скрипте | Использование в compose/API |
|------------|--------------------|-----------------------------|
| NEO4J_USER | константа `neo4j` | neo4j, api ✅ |
| NEO4J_PASSWORD | запрос | neo4j (NEO4J_AUTH), api ✅ |
| POSTGRES_DB/USER/PASSWORD | запрос + константы | postgres, api (POSTGRES_DSN) ✅ |
| TELEGRAM_BOT_TOKEN | запрос или placeholder | openclaw ✅ |
| LLM_MODEL, VLM_MODEL, … | константы в скрипте | api, openclaw (часть можно переопределить в Web UI) ✅ |
| EMBEDDING_DIM, QDRANT_COLLECTION | константы | api ✅ |
| OPENCLAW_AUTO_UPDATE | константа `false` | openclaw ✅ |
| SERVER_HOST, ACME_EMAIL | запрос | caddy ✅ |
| JWT_SECRET_KEY | openssl rand -hex 32 | api ✅ |
| JWT_EXPIRE_HOURS | константа 24 | api ✅ |
| CORS_ORIGINS | https://${SERVER_HOST} | api (при старте из БД/настроек) ✅ |

**Не задаются в install.sh (и не обязаны):** `JWT_ALGORITHM`, `provider_keys_encryption_secret`, `OPENCLAW_VERSION` — используются значения по умолчанию из кода/compose. ✅  

### 2.3 PostgreSQL

- **Схема при первой установке:** скрипты 01–05 смонтированы в `docker-entrypoint-initdb.d/` в compose. При первом запуске контейнера (пустой volume) они выполняются в алфавитном порядке. ✅  
- **01_init.sql:** расширение pgcrypto, таблицы каталогов/склада, функция `update_updated_at_column()`.  
- **02_users.sql:** таблицы users, chat_sessions, chat_messages, uploaded_files (зависит от функции из 01). ✅  
- **03_model_providers.sql:** провайдеры и назначения моделей. ✅  
- **04_provider_api_keys.sql:** колонка `encrypted_api_key`. ✅  
- **05_app_settings.sql:** таблица `app_settings`. ✅  
- Скрипт **не** вызывает `make init-pg` — при новой установке это верно. ✅  
- Ожидание готовности: `pg_isready -U enterprise -d enterprise_ai` (до 30 с). Имена совпадают с POSTGRES_USER и POSTGRES_DB из .env. ✅  

### 2.4 Создание пользователя admin

- Хэш: через `bcrypt.hashpw` в API-контейнере, пароль передаётся аргументом процесса (`sys.argv[1]`), что безопасно для спецсимволов. ✅  
- Таблица: `users` создаётся в 02_users.sql; поля `username`, `full_name`, `password_hash`, `role` соответствуют INSERT в скрипте. ✅  
- Конфликт: `ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash` — повторный запуск обновляет пароль. ✅  

**Безопасность:** перед подстановкой в SQL логин и полное имя экранируются через `sed "s/'/''/g"` (SAFE_USERNAME, SAFE_FULLNAME), что устраняет риск поломки запроса или инъекции при вводе кавычки в имени.

### 2.5 Neo4j

- Пароль передаётся в cypher-shell: `-p "${NEO4J_PASSWORD}"`. Значение из .env (после source). ✅  
- Файл init.cypher смонтирован в compose: `./infra/neo4j/init.cypher` → `/var/lib/neo4j/import/init.cypher`. ✅  
- Ожидание до 60 с, затем выполнение `--file .../init.cypher`. ✅  

### 2.6 Qdrant

- Инициализация через выполнение Python в API-контейнере: `qdrant_client.connect()` + `ensure_collection()`. ✅  
- Параметры Qdrant (хост, порт, коллекция, размерность) берутся из настроек приложения (БД или .env); к моменту вызова API уже загрузил настройки из БД. ✅  

### 2.7 Директории

- Скрипт создаёт `documents/{blueprints,manuals,gosts,emails,catalogs,tech_processes}` и `.gitkeep`. ✅  
- В compose API монтирует `./documents:/app/documents`. Путь совпадает. ✅  

---

## 3. Режим --teardown

- Условие: первый аргумент `--teardown`. ✅  
- Команда: `docker compose down -v --rmi local --remove-orphans`. Удаляются контейнеры, сети, volumes и локальные образы. ✅  
- Проверка наличия `docker-compose.yml` в текущей директории. ✅  
- Подтверждение перед выполнением. ✅  

---

## 4. Сценарий «существующий .env»

- Если `.env` уже есть, скрипт спрашивает «Перезаписать конфигурацию?». При отказе `_CONFIGURE` не устанавливается, шаг записи .env пропускается. ✅  
- Затем выполняется `set -a; source .env; set +a`. Переменные ADMIN_USERNAME, ADMIN_FULLNAME, ADMIN_PASSWORD в .env **не** записываются (секреты), поэтому при пропуске конфигурации они пусты. Создание admin не выполнится, выводится «Пароль admin не задан. Создайте пользователя вручную.» — поведение корректно. ✅  

---

## 5. Безопасность

- Запуск от root — необходим для установки пакетов и Docker. ✅  
- Пароли в .env записываются в кавычках через `escape_env_value` (экранирование `\` и `"`). ✅  
- JWT Secret генерируется через `openssl rand -hex 32`. ✅  
- Пароль admin не попадает в .env и не логируется. ✅  
- В SQL для admin подставляются значения из переменных; риск — только при наличии кавычек в имени/логине (см. п. 2.4).  

---

## 6. Несоответствия и рекомендации

### 6.1 make openclaw-pair

В блоке «Следующие шаги» указано: «Подключите Telegram-бота: `make openclaw-pair`». В Makefile добавлена цель `openclaw-pair`, выводящая краткую подсказку по настройке Telegram (TELEGRAM_BOT_TOKEN в .env, перезапуск openclaw). ✅ Исправлено.

### 6.2 Экранирование имён в SQL при создании admin

При вводе логина или полного имени с символом `'` (например, `O'Brien`) SQL-запрос ломается или может привести к инъекции.  

**Исправлено:** перед подстановкой в psql скрипт формирует SAFE_USERNAME и SAFE_FULLNAME через `sed "s/'/''/g"`. ✅

### 6.3 Порядок шагов в комментарии в начале скрипта

В шапке было указано: «8. Создаёт пользователя admin», «9. Ждёт готовности PostgreSQL». Пункты 8 и 9 приведены в соответствие с кодом (сначала ожидание PostgreSQL, затем создание admin). ✅ Исправлено.

### 6.4 Ollama не собирается

Образы ollama-gpu и ollama-cpu не собираются, а тянутся из Docker Hub. При первом `up` они загружаются автоматически. Никаких правок не требуется, но в аудите зафиксировано. ✅  

---

## 7. Итоговая таблица

| Проверка | Статус |
|----------|--------|
| Соответствие docker-compose (сервисы, env, volumes) | ✅ |
| Соответствие .env и .env.example (критичные переменные) | ✅ |
| PostgreSQL: initdb.d 01–05, без лишнего init-pg при новой установке | ✅ |
| Создание admin: bcrypt, таблица users, экранирование кавычек в SQL | ✅ |
| Neo4j: пароль, init.cypher | ✅ |
| Qdrant: ensure_collection через API | ✅ |
| Директории documents/* | ✅ |
| Режим --teardown | ✅ |
| Сценарий «существующий .env» | ✅ |
| Безопасность (пароли, JWT, экранирование .env) | ✅ (п. 6.2 — улучшение) |
| Документация в скрипте (шаги 8–9, make openclaw-pair) | ✅ исправлено |

---

## 8. Внесённые правки (по результатам аудита)

1. **Порядок в комментарии:** в шапке install.sh пункты 8 и 9 приведены в соответствие с кодом (сначала ожидание PostgreSQL, затем создание admin).  
2. **make openclaw-pair:** в Makefile добавлена цель `openclaw-pair`, выводящая подсказку по настройке Telegram.  
3. **SQL при создании admin:** перед подстановкой в psql формируются SAFE_USERNAME и SAFE_FULLNAME через `sed "s/'/''/g"` (экранирование одинарных кавычек для PostgreSQL).

Установка через `install.sh` после указанных правок соответствует текущей инфраструктуре и рекомендациям аудита.
