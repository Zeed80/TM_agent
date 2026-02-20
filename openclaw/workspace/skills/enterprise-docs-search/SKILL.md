---
name: enterprise-docs-search
description: >
  Поиск по технической документации завода (паспорта станков, инструкции по
  эксплуатации, ГОСТы, техпроцессы, деловые письма). Hybrid Search: BM25 + Dense.
user-invocable: false
---

# Enterprise Docs Search — Поиск по документации завода

## Когда использовать этот навык

Используй ЭТОТ навык когда пользователь спрашивает о:
- Настройке или эксплуатации конкретного станка (токарный 16К20, фрезерный и т.д.)
- Параметрах режимов резания из паспорта станка
- Требованиях ГОСТ к материалам, допускам, шероховатостям
- Содержании деловых писем или переписки
- Описаниях техпроцессов в текстовом виде
- Инструкциях по наладке или обслуживанию оборудования

## Как вызвать

```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/docs-search \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"<ВОПРОС_ПОЛЬЗОВАТЕЛЯ>\"}"
```

Для фильтрации по типу источника добавь `source_filter`:
- `"manual"` — паспорта и инструкции по эксплуатации
- `"gost"` — ГОСТы и стандарты
- `"blueprint"` — описания чертежей
- `"email"` — деловая переписка

```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/docs-search \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"<ВОПРОС>\", \"source_filter\": \"manual\"}"
```

## Интерпретация ответа

```json
{
  "answer": "Синтезированный ответ из документации",
  "sources": [{"source": "Паспорт 16К20.pdf, стр. 45", "text": "..."}],
  "chunks_found": 8
}
```

Передай пользователю `answer`. При необходимости укажи источники из `sources`.

## Примеры

**Пример 1 — настройка станка:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/docs-search \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Как настроить гитару токарно-винторезного 16К20 для нарезки дюймовой резьбы?\", \"source_filter\": \"manual\"}"
```

**Пример 2 — требования ГОСТ:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/docs-search \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Допуски на посадку H7/k6 по ГОСТ\"}"
```

## Обработка ошибок

Если `chunks_found: 0` — документы не загружены в систему или не найдены.
Сообщи пользователю и рекомендуй добавить документацию через ETL-пайплайн.
