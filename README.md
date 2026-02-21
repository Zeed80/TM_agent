<div align="center">

# 🏭 Enterprise AI Assistant

### Локальная AI-система для автоматизации работы ИТР на производственном предприятии

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha%20%E2%80%94%20In%20Development-orange)](https://github.com/Zeed80/TM_agent)
[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![Ollama](https://img.shields.io/badge/Ollama-Qwen3:30b-black?logo=ollama)](https://ollama.ai)

</div>

---

> [!WARNING]
> **⚠ ПРОЕКТ НАХОДИТСЯ В АКТИВНОЙ РАЗРАБОТКЕ**
>
> Данный репозиторий — работающий прототип, который активно развивается. API, схемы БД и структура конфигурации могут изменяться между версиями без сохранения обратной совместимости. **Не рекомендуется использовать в критических production-средах без предварительного тестирования.**
>
> Мы принимаем issues, pull requests и предложения по улучшению.

---

## Что это такое

**Enterprise AI Assistant** — самодостаточная AI-платформа, которая разворачивается на локальном сервере предприятия и позволяет инженерно-техническому персоналу (ИТР) работать с производственными данными на естественном языке.

Система **полностью работает офлайн** — никакие данные не покидают периметр предприятия. Все AI-модели запускаются локально через [Ollama](https://ollama.ai).

### Ключевые сценарии использования

| Сценарий | Что делает система |
|---|---|
| **Анализ чертежей** | Распознаёт материал, размеры, допуски с PNG/JPEG чертежей через VLM |
| **Поиск по документации** | Семантический поиск по паспортам станков, ГОСТам, инструкциям |
| **Работа со складом** | Text-to-SQL запросы к остаткам материалов и инструмента |
| **Производственный граф** | Text-to-Cypher по связям: станки → оснастка → техпроцессы |
| **Документооборот** | Анализ деловой переписки, техпроцессов, нормативных документов |

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                     Браузер (HTTPS)                          │
│              React 19 SPA + Tailwind CSS 4                   │
└─────────────────────────┬────────────────────────────────────┘
                          │ JWT Auth + SSE Chat + REST
┌─────────────────────────▼────────────────────────────────────┐
│                 Caddy (Reverse Proxy)                        │
│          Auto HTTPS: Let's Encrypt / self-signed             │
└──────┬──────────────────────────────────────┬───────────────┘
       │ /api/*                               │ /*
┌──────▼──────────────────────┐   ┌───────────▼──────────────┐
│   Python FastAPI 0.115      │   │   Vite React Dev Server  │
│                             │   │   (frontend:3000)        │
│  ┌─ Auth & Users (JWT)      │   └──────────────────────────┘
│  ├─ Chat (SSE + Agentic)    │
│  ├─ Files Upload            │
│  ├─ System Status           │
│  ├─ Admin (Docker control)  │
│  │                          │
│  └─ Skills (internal):      │
│     ├── graph_search    ────┼──▶ Neo4j 5 (Text-to-Cypher)
│     ├── docs_search     ────┼──▶ Qdrant (BM25 + Dense)
│     ├── blueprint_vision────┼──▶ Qwen3-VL:14b (VLM)
│     └── inventory_sql   ────┼──▶ PostgreSQL (Text-to-SQL)
└─────────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
Ollama GPU   Ollama CPU    OpenClaw
Qwen3:30b    qwen3-embed   (Telegram
Qwen3-VL:14b qwen3-rerank   агент)
```

### Agentic Loop (Chat)

Чат работает по агентному принципу: LLM сам выбирает, какие инструменты вызывать для ответа на вопрос пользователя.

```
User → SSE stream → FastAPI → Ollama (tool_calls) → Skills → Ollama → Token stream → User
                                    ↕ до 5 итераций
                              [graph, docs, sql, vision]
```

---

## Стек технологий

<table>
<tr>
<td valign="top" width="50%">

### Backend
- **Python 3.12** + FastAPI 0.115
- **Ollama** — Qwen3:30b (LLM), Qwen3-VL:14b (VLM)
- **Qdrant** — гибридный поиск (BM25 + Dense)
- **Neo4j 5** — граф производственных знаний
- **PostgreSQL 17** — склад, пользователи, история чатов
- **SSE** — потоковый ответ AI
- **JWT** — аутентификация, роли (admin/user)
- **Docker SDK** — управление контейнерами из UI

</td>
<td valign="top" width="50%">

### Frontend
- **React 19** + TypeScript 5 + Vite 6
- **Tailwind CSS 4** — тёмная enterprise-тема
- **Zustand** — state management
- **TanStack Query v5** — server state
- **React Router v7** — маршрутизация
- **Lucide React** — иконки

### Инфраструктура
- **Caddy 2.9** — HTTPS reverse proxy (Let's Encrypt)
- **OpenClaw** — Telegram-агент (опционально)
- **Docker Compose** — оркестрация 9 сервисов

</td>
</tr>
</table>

---

## Требования к серверу

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| **ОС** | Ubuntu 24.04 LTS | Ubuntu 25.10 |
| **GPU** | NVIDIA 16GB VRAM | RTX 3090 24GB |
| **RAM** | 32GB | 64GB DDR5 |
| **CPU** | 8 ядер | AMD Ryzen 9 9900X |
| **Диск** | 100GB SSD | 500GB NVMe |
| **Сеть** | Интернет для установки | Домен + 80/443 открыты |

> **CPU-only режим:** Система запустится без GPU, но LLM и VLM будут работать значительно медленнее.

---

## Быстрый старт

### Вариант 1: Автоматическая установка (рекомендуется)

```bash
git clone https://github.com/Zeed80/TM_agent.git
cd TM_agent
chmod +x install.sh
sudo bash install.sh
```

Скрипт автоматически:
- Установит Docker Engine + NVIDIA Container Toolkit
- Запросит домен/IP, пароли, email для Let's Encrypt
- Создаст `.env`, соберёт образы, запустит сервисы
- Создаст пользователя admin
- Инициализирует схемы БД

### Вариант 2: Ручная установка

<details>
<summary>Развернуть шаги</summary>

#### 1. Docker + NVIDIA Container Toolkit

```bash
# Docker
curl -fsSL https://get.docker.com | bash
sudo systemctl enable docker --now
sudo usermod -aG docker $USER

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

#### 2. Конфигурация

```bash
git clone https://github.com/Zeed80/TM_agent.git && cd TM_agent
cp .env.example .env
```

Отредактируй `.env`:
```env
# Домен или IP сервера (Caddy настроит HTTPS автоматически)
SERVER_HOST=ai.example.com
ACME_EMAIL=admin@example.com

# Пароли
NEO4J_PASSWORD=your_neo4j_password
POSTGRES_PASSWORD=your_pg_password

# JWT (генерируй: openssl rand -hex 32)
JWT_SECRET_KEY=your_secret_key
```

#### 3. Запуск

```bash
make up
make pull-models   # ~40GB, требует интернета
make init-db       # Neo4j схема
make init-qdrant   # Qdrant коллекция
make create-admin  # Пользователь admin
```

</details>

---

## Веб-интерфейс

После установки открой `https://YOUR_DOMAIN` (или `https://IP`):

| Страница | Описание |
|---|---|
| **`/login`** | Вход с JWT-аутентификацией |
| **`/chat`** | AI-чат с агентным поиском по всем источникам данных |
| **`/upload`** | Загрузка документов: чертежи, PDF, Excel, ТП |
| **`/status`** | Состояние сервисов, VRAM, модели |
| **`/admin`** | 🔒 Управление Docker-контейнерами, live-логи, метрики |
| **`/users`** | 🔒 Управление пользователями и ролями |

> 🔒 — только для пользователей с ролью `admin`

### Скриншот интерфейса

```
┌─────────────────────────────────────────────────────┐
│ 🏭 Enterprise AI  [Chat] [Docs] [Status] [Admin]   │
├──────────────┬──────────────────────────────────────┤
│ Сессии       │ Чат с AI                             │
│ ─────────    │                                      │
│ ▶ Токарный   │  User: Сколько PA6-GF30 на складе?  │
│   16К20      │                                      │
│ · ТПА-5000   │  AI: 🔍 Ищу в базе...               │
│              │  ⚙ inventory_sql_search              │
│ + Новый чат  │                                      │
│              │  Остаток PA6-GF30: 847 кг           │
│              │  (последнее поступление 15.02.2026)  │
│              │ ________________________             │
│              │ [Введите вопрос...] [Отправить]      │
└──────────────┴──────────────────────────────────────┘
```

---

## Структура документов

Положи файлы в соответствующие папки перед индексацией:

```
documents/
├── blueprints/       # Чертежи PNG/JPEG → VLM-анализ → Neo4j + Qdrant
├── manuals/          # Паспорта станков PDF/DOCX → Qdrant
├── gosts/            # ГОСТы PDF → Qdrant
├── catalogs/         # Инструмент/материалы Excel → PostgreSQL
│   ├── tools_*.xlsx
│   ├── metals_*.xlsx
│   └── polymers_*.xlsx
├── tech_processes/   # Техпроцессы Excel → Neo4j
│   └── ТП-001_Корпус.xlsx
└── emails/           # Деловая переписка .eml → Qdrant
```

```bash
make ingest-all     # Запустить все ETL-пайплайны
# или через Admin panel в браузере
```

---

## Управление

### Из браузера (`/admin`)
- Просмотр статуса всех контейнеров (CPU%, RAM)
- Рестарт / стоп / запуск отдельных сервисов
- Live-логи любого контейнера (SSE поток)
- Загрузка Ollama моделей с прогрессом
- Запуск ETL-задач индексации

### Из командной строки

```bash
make status          # Статус + URL доступа
make logs            # Логи API
make logs-caddy      # Логи HTTPS (Let's Encrypt)
make update          # Обновить все сервисы
make update-api      # Пересобрать только API
make backup-pg       # Дамп PostgreSQL
make create-admin    # Сбросить пароль admin
make down            # Остановить всё
make clean           # Удалить контейнеры и volumes (данные — необратимо!)
make teardown        # Полная очистка: контейнеры, volumes, образы проекта (чистый старт)
```

### Чистая переустановка

Если после частых переустановок контейнеры не поднимаются (unhealthy, dependency failed), сделай полный сброс:

```bash
make teardown        # подтверди вводом yes
# Затем заново поднять и при необходимости пересобрать образы:
make up              # или: docker compose build && docker compose up -d
make pull-models     # при первом запуске
make init-db        # при первом запуске
```

`teardown` удаляет контейнеры, сети, все volumes и образы проекта (tm_agent-api, tm_agent-frontend и т.д.). Базовые образы (postgres, neo4j, qdrant, ollama) при следующем `make up` подтянутся заново.

---

## Прямое тестирование навыков (без UI)

```bash
# Поиск по граф-базе знаний
curl -X POST https://YOUR_DOMAIN/api/v1/skills/graph-search \
  -H "Content-Type: application/json" \
  -d '{"question": "Покажи все ТПА и их оснастку"}'

# Семантический поиск по документам
curl -X POST https://YOUR_DOMAIN/api/v1/skills/docs-search \
  -H "Content-Type: application/json" \
  -d '{"question": "Как нарезать дюймовую резьбу на 16К20?"}'

# Анализ чертежа через VLM
curl -X POST https://YOUR_DOMAIN/api/v1/skills/blueprint-vision \
  -H "Content-Type: application/json" \
  -d '{"image_path": "/app/documents/blueprints/detail_001.png"}'

# SQL-запрос к складу
curl -X POST https://YOUR_DOMAIN/api/v1/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d '{"question": "Остаток полиамида 6 на складе"}'
```

API документация: `https://YOUR_DOMAIN/docs` (Swagger UI)

---

## Структура проекта

```
TM_agent/
├── 📄 docker-compose.yml        # Оркестрация 9 сервисов
├── 📄 .env.example              # Шаблон конфигурации
├── 📄 Makefile                  # CLI управление
├── 📄 install.sh                # Автоматическая установка
│
├── 📁 api/                      # Python FastAPI
│   ├── src/
│   │   ├── ai_engine/           # LLM/VLM/Embedding/Reranker + VRAMManager
│   │   ├── db/                  # Neo4j / Qdrant / PostgreSQL клиенты
│   │   ├── routers/             # Навыки + Auth + Chat + Files + Admin
│   │   └── models/              # Pydantic модели
│   └── requirements.txt
│
├── 📁 frontend/                 # React 19 SPA
│   └── src/
│       ├── pages/               # Chat, Upload, Status, Admin, Users, Login
│       ├── components/          # AppLayout, Sidebar, MessageBubble
│       ├── store/               # Zustand: auth, chat
│       └── api/                 # API client (JWT + SSE + upload)
│
├── 📁 ingestion/                # ETL пайплайны
│   └── src/
│       ├── excel_ingestion.py   # Excel → PostgreSQL
│       ├── pdf_text_ingestion.py# PDF/DOCX → Qdrant
│       ├── blueprint_ingestion.py# PNG → VLM → Neo4j + Qdrant
│       └── tech_process_ingestion.py
│
├── 📁 infra/
│   ├── caddy/                   # Caddy + auto-HTTPS entrypoint
│   ├── postgres/                # DDL схемы (таблицы, индексы)
│   ├── neo4j/                   # Cypher schema (constraints, indexes)
│   └── qdrant/                  # Collection setup
│
├── 📁 openclaw/                 # OpenClaw Telegram-агент (опционально)
│   └── workspace/               # SOUL.md, AGENTS.md, SKILL.md навыки
│
└── 📁 documents/                # Загружаемые документы (gitignored)
    ├── blueprints/
    ├── manuals/
    ├── gosts/
    ├── catalogs/
    ├── tech_processes/
    └── emails/
```

---

## Безопасность

- Все пользовательские запросы аутентифицируются через **JWT Bearer tokens**
- Пароли хранятся в виде **bcrypt-хэшей** (passlib, cost factor 12)
- `/skills/*` endpoints **заблокированы** на уровне Caddy (только внутренний доступ)
- Docker socket монтируется **read-only** (`ro`) — только для мониторинга
- HTTPS обязателен — HTTP автоматически редиректится на HTTPS
- Конфигурация через `.env` файл (в `.gitignore`)

---

## Компоненты и лицензии

| Компонент | Лицензия | Использование |
|---|---|---|
| Ollama | MIT | Как сервис (Docker) |
| Qwen3 модели | Apache 2.0 / Tongyi | Как AI-модели |
| Qdrant | Apache 2.0 | Как сервис (Docker) |
| Neo4j CE | GPL v3 | Как сервис (Docker), не линкуется |
| PostgreSQL | PostgreSQL License | Как сервис (Docker) |
| FastAPI | MIT | Python библиотека |
| React | MIT | Frontend библиотека |
| Caddy | Apache 2.0 | Как сервис (Docker) |
| OpenClaw | MIT | Как сервис (Docker) |

> Данный проект использует все внешние системы **исключительно как сервисы через сетевые протоколы** (Docker), не связывая их код. Neo4j CE (GPL v3) используется только как сетевой сервис, что не накладывает GPL-требований на данный репозиторий.

---

## Вклад в проект

Приветствуются issues и pull requests! Особенно интересны:

- 🔌 Новые источники данных (SAP, 1С, ERP-системы)
- 🧠 Поддержка других LLM-моделей (DeepSeek, Mistral, Llama)
- 🌐 Интернационализация UI (English, Deutsch)
- 📊 Дашборды аналитики производства
- 🔐 SSO / LDAP / Active Directory интеграция
- 🧪 Тесты (unit, integration)

```bash
# Локальная разработка
cp .env.example .env
make up              # Поднимает все сервисы
# API авто-перезагружается при изменении src/
# Frontend HMR работает мгновенно
```

---

## Дорожная карта

- [x] Python FastAPI + 4 AI-навыка
- [x] React Web UI с тёмной темой
- [x] JWT аутентификация + роли
- [x] SSE стриминг + agentic loop
- [x] HTTPS через Caddy (Let's Encrypt)
- [x] Admin panel (Docker control + live logs)
- [x] Автоматический install.sh
- [ ] Тесты (unit + integration)
- [ ] Docker Hub образы (без сборки)
- [ ] Telegram Mini App
- [ ] SAP / 1С коннекторы
- [ ] Мультиязычный UI
- [ ] Kubernetes Helm chart

---

## Лицензия

```
MIT License

Copyright (c) 2026 Zeed80

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

Полный текст: [LICENSE](LICENSE)

---

<div align="center">


[⭐ Поставить звезду](https://github.com/Zeed80/TM_agent) · [🐛 Сообщить о проблеме](https://github.com/Zeed80/TM_agent/issues) · [💡 Предложить улучшение](https://github.com/Zeed80/TM_agent/issues)

</div>
