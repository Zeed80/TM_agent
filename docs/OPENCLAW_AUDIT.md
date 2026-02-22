# Аудит OpenClaw в проекте TM_agent

**Дата:** 22.02.2025  
**Цель:** Полная инспекция использования OpenClaw — настройка, скиллы, интеграция с API и Web UI.

---

## 1. Роль OpenClaw в проекте

По PRD (`project_prd.md`):

- **Оркестратор:** OpenClaw — ядро агента и точка интеграции с мессенджерами (Telegram, локальный чат).
- **Навыки:** Вся логика доступа к базам (Neo4j, Qdrant, PostgreSQL) и VLM оформлена как **Skills** в `workspace/skills/`.
- **Модель:** LLM (Qwen3:30b) в OpenClaw решает, какой навык вызвать; выполнение — через **curl** к Python API (`api:8000`).

Схема: **Пользователь → OpenClaw (LLM) → выбор скилла → bash/curl → FastAPI /skills/* → БД/LLM/VLM → ответ**.

---

## 2. Настройка и конфигурация

### 2.1 Docker

- **Сервис:** `docker-compose.yml` — сервис `openclaw` (порт **18789**).
- **Образ:** `openclaw/docker/Dockerfile` — Node.js 22, глобальная установка `openclaw@${OPENCLAW_VERSION}` (по умолчанию `latest`), curl, jq, git.
- **Тома:**
  - `./openclaw/workspace` → `/root/.openclaw/workspace` (SOUL.md, AGENTS.md, **skills/**).
  - `./openclaw` → `/opt/openclaw-config:ro` (откуда в entrypoint копируется `openclaw.json` при наличии).
  - `openclaw_data` → `/root/.openclaw/credentials` (учётные данные мессенджеров).
- **Зависимости:** `api` (healthy), `ollama-gpu` (healthy).
- **Переменные:** `TELEGRAM_BOT_TOKEN`, `OPENCLAW_AUTO_UPDATE` (по умолчанию `false`).

### 2.2 Entrypoint (`openclaw/docker/entrypoint.sh`)

- При `OPENCLAW_AUTO_UPDATE=true` — перед запуском выполняется `npm install -g openclaw@latest`.
- Конфиг:
  - Если на хосте есть `openclaw/openclaw.json` — он копируется в `/root/.openclaw/openclaw.json`.
  - Иначе генерируется дефолтный JSON:
    - при заданном `TELEGRAM_BOT_TOKEN` — Telegram включён, **токен подставляется из env** (исправлено в аудите);
    - иначе — Telegram выключен.
- Запуск: `openclaw gateway --port 18789`.

### 2.3 Запуск штатной настройки после развёртывания

При старте контейнера OpenClaw в entrypoint автоматически выполняется:

1. **`openclaw doctor --fix --non-interactive`** — нормализация конфига, миграции схемы, проверка состояния.
2. **`openclaw doctor --generate-gateway-token`** (если поддерживается версией) — генерация ключа доступа к Control UI (`gateway.auth.token`). Если флаг недоступен, токен создаётся при первом запуске gateway.
3. **Запуск gateway** на порту 18789.

Чтобы **получить ссылку с токеном на вход** в веб-интерфейс OpenClaw:

- Откройте в браузере **`https://<ваш-домен>/openclaw/__openclaw__/canvas/`** (или пункт «OpenClaw» в сайдбаре приложения).
- Пройдите первоначальную настройку в Control UI; в конце будет выдана постоянная ссылка с токеном — сохраните её для быстрого входа.

Без этого шага вход в OpenClaw по веб-интерфейсу недоступен (токен хранится в конфиге внутри контейнера и не выводится в логи из соображений безопасности).

### 2.4 Нужно ли настраивать OpenClaw после установки?

**Минимальный сценарий (без ручной настройки):**

- В `.env` заданы **`TELEGRAM_BOT_TOKEN`** (если нужен Telegram) и **`LLM_MODEL`** (по умолчанию `qwen3:30b` в `.env.example`).
- Контейнеру OpenClaw передаются **`LLM_MODEL`** и **`OLLAMA_API_KEY`**; в entrypoint при отсутствии `openclaw.json` собирается дефолтный конфиг с провайдером Ollama (`http://ollama-gpu:11434`) и моделью `ollama/${LLM_MODEL}`.
- Тогда **отдельно настраивать OpenClaw после установки не нужно** — агент сразу использует Ollama и выбранную модель. Для доступа к веб-интерфейсу один раз откройте canvas (см. выше) и сохраните ссылку с токеном.

**Когда нужна ручная настройка:**

- Другая модель или провайдер (не Ollama), другой URL Ollama, fallback-модели, отключение автообновления и т.п. — создайте **`openclaw/openclaw.json`** по [документации OpenClaw](https://docs.openclaw.ai). При наличии файла на хосте он копируется в контейнер и подменяет сгенерированный дефолт.
- Итог: **модель и провайдер по умолчанию задаются из .env; при необходимости тонкой настройки — через свой `openclaw.json`.**

### 2.5 Файл openclaw.json на хосте

- В репозитории **нет** `openclaw/openclaw.json` (исключён в `.gitignore`: `openclaw/*.json`).
- Если нужна кастомная конфигурация (доп. каналы, навыки, другой провайдер/модель) — создайте `openclaw/openclaw.json` по [документации OpenClaw](https://docs.openclaw.ai). При старте контейнера он будет скопирован в контейнер и **полностью заменит** сгенерированный дефолт (в т.ч. Ollama и модель из .env).

### 2.6 Переменные окружения (.env / .env.example)

- `TELEGRAM_BOT_TOKEN` — токен бота для OpenClaw (опционально).
- `LLM_MODEL` — модель для агента (например `qwen3:30b`); подставляется в дефолтный конфиг OpenClaw как `ollama/${LLM_MODEL}`.
- `OPENCLAW_AUTO_UPDATE` — автообновление OpenClaw при рестарте контейнера.

---

## 3. Workspace OpenClaw

Расположение в контейнере: `/root/.openclaw/workspace` (на хосте: `openclaw/workspace/`).

### 3.1 Файлы идентичности и контракта

| Файл         | Назначение |
|-------------|------------|
| **SOUL.md** | Персона: «Ярослав», ценности (точность, практичность), ограничения. |
| **IDENTITY.md** | Имя, роль (ИТР-ассистент), специализация (станки, ТПА, чертежи, ГОСТы), стиль общения. |
| **AGENTS.md** | Операционный контракт: таблица «тип вопроса → навык», правила (комбинировать скиллы, указывать источник, язык — русский). |

Эти файлы задают поведение агента и когда какой навык вызывать.

### 3.2 Навыки (Skills)

Все скиллы — каталоги в `workspace/skills/` с файлом **SKILL.md** (YAML frontmatter + Markdown-инструкции). Формат совместим с [OpenClaw Skills](https://docs.openclaw.ai/tools/skills).

| Навык (name)             | Назначение | Эндпоинт API |
|--------------------------|------------|--------------|
| **enterprise-graph-search** | Граф Neo4j: маршруты, оснастка, станки, техпроцессы | `POST /skills/graph-search` |
| **enterprise-docs-search**  | Документы (Qdrant): паспорта, ГОСТы, инструкции     | `POST /skills/docs-search`  |
| **inventory-sql-search**    | Склад PostgreSQL: остатки, номенклатура            | `POST /skills/inventory-sql`|
| **blueprint-vision**       | Анализ чертежей (VLM)                              | `POST /skills/blueprint-vision` |

Во всех SKILL.md:

- **user-invocable: false** — вызываются только агентом по контракту из AGENTS.md.
- Описаны «Когда использовать», «Как вызвать» (примеры curl с `http://api:8000/skills/...`), формат ответа JSON и обработка ошибок.

Вызов из OpenClaw: LLM выполняет команду из SKILL.md (bash с curl). Сеть Docker даёт доступ по имени `api` к контейнеру API.

---

## 4. Интеграция с Python API

### 4.1 Роутеры навыков (`api/src/main.py`)

Под префиксом `/skills` подключены:

- `graph_search.router` → `/skills/graph-search`
- `docs_search.router` → `/skills/docs-search`
- `inventory_sql.router` → `/skills/inventory-sql`
- `blueprint_vision.router` → `/skills/blueprint-vision`

Запросы от OpenClaw идут на `http://api:8000/skills/...` (из контейнера openclaw).

### 4.2 Соответствие SKILL.md и API

- **graph-search:** тело `{"question": "..."}` → ответ `answer`, `records_count`, `cypher_used` — совпадает с SKILL.md.
- **docs-search:** тело `{"question": "...", "source_filter": "manual"|"gost"|...}` → ответ `answer`, `sources`, `chunks_found` — совпадает.
- **inventory-sql:** тело `{"question": "..."}` → ответ `answer`, `rows_count`, `raw_results` — совпадает.
- **blueprint-vision:** тело `{"image_path": "...", "question": "..."}` → ответ `answer`, `image_path` — совпадает. В SKILL.md указан путь на сервере `/app/documents/blueprints/`; внутри Docker путь к файлам должен быть доступен API (общий том или копирование).

---

## 5. Web UI (чат) и вызов навыков

В `api/src/routers/chat_router.py` реализован agentic loop: LLM выбирает инструменты, исполнитель вызывает **внутренние** навыки через HTTP к `http://localhost:8000` (тот же API).

- **Маппинг инструментов на эндпоинты** (до исправлений в аудите):
  - `enterprise_graph_search` → `/skills/graph-search` ✅
  - `enterprise_docs_search`  → `/skills/docs-search` ✅
  - `inventory_sql_search`   → **было** `/skills/inventory-sql-search` ❌ → **исправлено на** `/skills/inventory-sql` ✅
  - `blueprint_vision`       → `/skills/blueprint-vision` ✅

- **Резюме для docs-search:** раньше использовалось `data.get("documents", [])`, тогда как API возвращает `sources` и `chunks_found`. **Исправлено:** резюме строится по `chunks_found` / `sources`.

---

## 6. Внесённые исправления (по результатам аудита)

1. **chat_router.py:** для инструмента `inventory_sql_search` эндпоинт заменён с `/skills/inventory-sql-search` на `/skills/inventory-sql` (соответствует реальному роуту).
2. **chat_router.py:** для `enterprise_docs_search` резюме строится по `chunks_found` и `sources`, а не по несуществующему полю `documents`.
3. **openclaw/docker/entrypoint.sh:** при генерации дефолтного конфига с Telegram токен подставляется из env: heredoc без кавычек (`<< ENDOFCONFIG`), чтобы подставлялся `$TELEGRAM_BOT_TOKEN`.

---

## 7. Рекомендации и замечания

### 7.1 Конфигурация

- При необходимости тонкой настройки (Ollama URL, список навыков, каналы) — добавить в репозиторий пример `openclaw/openclaw.json.example` и описать в README.
- Убедиться, что в production `OPENCLAW_AUTO_UPDATE` задан осознанно (например, `false` для воспроизводимости).

### 7.2 Скиллы

- Все четыре скилла согласованы с API и AGENTS.md; таблица в AGENTS.md однозначно задаёт тип вопроса → навык.
- **blueprint-vision:** в SKILL.md указан таймаут 60–90 с из-за переключения VLM; curl в скилле уже с `--max-time 120`. Убедиться, что таймауты на стороне API и OpenClaw не меньше.

### 7.3 Безопасность и сеть

- OpenClaw и API в одной Docker-сети; с хоста к OpenClaw — порт 18789. При публикации порта — учесть доступ только с доверенных адресов/фасада (Caddy).
- Токен Telegram не должен попадать в логи; в текущей схеме он только в env и в сгенерированном openclaw.json внутри контейнера — ок.

### 7.4 Дальнейшая проверка

- Прогнать сценарии из PRD (термопластавтомат, универсальный станок) через Telegram-бота и через Web UI чат и убедиться, что все четыре навыка вызываются и возвращают ожидаемые ответы.
- При добавлении нового навыка: создать каталог в `workspace/skills/<name>/` с SKILL.md, добавить роутер под `/skills/...` в API и строку в таблицу в AGENTS.md.

---

## 8. Краткая схема потока

```
[Пользователь]
      │
      ▼
[OpenClaw Gateway :18789]
      │ SOUL.md, IDENTITY.md, AGENTS.md
      │ LLM (Ollama qwen3:30b) выбирает навык
      ▼
[Выполнение команды из SKILL.md]
      │ curl -X POST http://api:8000/skills/<skill> -d '{"question":...}'
      ▼
[FastAPI /skills/*]
      │ graph_search, docs_search, inventory_sql, blueprint_vision
      ▼
[Neo4j / Qdrant / PostgreSQL / VLM]
      │
      ▼
[JSON-ответ] → OpenClaw → ответ пользователю
```

---

**Итог:** OpenClaw настроен как оркестратор с четырьмя кастомными скиллами, конфигурация через env и опциональный `openclaw.json`, workspace и контракт в AGENTS.md согласованы с API. Исправлены ошибки в chat_router (эндпоинт inventory-sql и резюме docs-search) и подстановка Telegram-токена в entrypoint.
