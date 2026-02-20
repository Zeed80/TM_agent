---
name: inventory-sql-search
description: >
  Поиск по складу и номенклатуре через PostgreSQL. Остатки инструмента,
  металлов и полимеров. Text-to-SQL через Qwen3:30b.
user-invocable: false
---

# Inventory SQL Search — Склад и номенклатура

## Когда использовать этот навык

Используй ЭТОТ навык когда пользователь спрашивает о:
- Наличии инструмента на складе (фрезы, резцы, сверла, метчики)
- Остатках металла по марке (сталь 45, 40Х, 12Х18Н10Т...)
- Остатках полимеров (полиамид, ABS, PP...)
- Зарезервированных позициях
- Местонахождении позиции на складе (стеллаж, секция)
- Параметрах полимеров (температура переработки, усадка, MFI)
- Характеристиках металлов (твёрдость, предел прочности)

## Как вызвать

```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"<ВОПРОС_О_СКЛАДЕ>\"}"
```

## Интерпретация ответа

```json
{
  "answer": "На складе есть 250 кг Полиамида 6 (марка PA6 B3)...",
  "rows_count": 3,
  "raw_results": [...]
}
```

Передай пользователю `answer`. При необходимости уточни из `raw_results`.

## Примеры

**Пример 1 — остаток полимера:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Сколько Полиамида 6 есть на складе и хватит ли на 5000 втулок весом 50г каждая?\"}"
```

**Пример 2 — поиск инструмента:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Есть ли концевые фрезы D10 с покрытием TiAlN на складе?\"}"
```

**Пример 3 — низкие остатки:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Покажи все материалы с остатком менее 100 кг\"}"
```

**Пример 4 — параметры полимера для ТПА:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/inventory-sql \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Какая температура переработки и усадка у полиамида PA6-GF30?\"}"
```

## Обработка ошибок

- `rows_count: 0` — позиция не найдена. Предложи проверить написание марки или названия.
- `422` — SQL-запрос нарушил правила безопасности. Переформулируй вопрос.
- `502` — ошибка подключения к БД. Попробуй позже.

Никогда не угадывай остатки самостоятельно. Только данные из системы.
