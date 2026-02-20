---
name: blueprint-vision
description: >
  Анализ чертежей через VLM (Qwen3-VL:14b). Принимает путь к изображению чертежа
  и возвращает технические требования: размеры, допуски, материал, шероховатости.
  ВНИМАНИЕ: Переключение GPU-модели занимает до 90 секунд — это нормально.
user-invocable: false
---

# Blueprint Vision — Анализ чертежей

## Когда использовать этот навык

Используй ЭТОТ навык когда:
- Пользователь прислал или упомянул чертёж и хочет узнать его требования
- Нужно извлечь: материал, допуски, шероховатости, размеры, ТТ
- Нужно понять чертёж перед поиском оснастки или техпроцесса

## ВАЖНО: таймаут

Этот навык переключает GPU-модель (LLM → VLM). Это занимает 60-90 секунд.
`--max-time 120` в curl обязателен. Не прерывай выполнение раньше времени.

## Формат пути к файлу

Файлы чертежей хранятся на сервере в папке `/app/documents/blueprints/`.
Полный путь: `/app/documents/blueprints/имя_файла.png`

## Как вызвать

**Полный анализ чертежа (все технические требования):**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/blueprint-vision \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"/app/documents/blueprints/<ИМЯ_ФАЙЛА.png>\"}"
```

**Конкретный вопрос по чертежу:**
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/blueprint-vision \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"/app/documents/blueprints/<ИМЯ_ФАЙЛА.png>\", \"question\": \"<ВОПРОС>\"}"
```

## Интерпретация ответа

```json
{
  "answer": "**ОСНОВНАЯ ИНФОРМАЦИЯ:**\n- Номер чертежа: 123-456\n...",
  "image_path": "/app/documents/blueprints/чертеж.png"
}
```

Передай пользователю содержимое поля `answer`.

## Примеры

**Пример 1 — полный анализ:**
Пользователь: "Проанализируй чертёж №123 по детали втулка"
Если файл называется `vtulka_123.png`:
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/blueprint-vision \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"/app/documents/blueprints/vtulka_123.png\"}"
```

**Пример 2 — целевой вопрос:**
Пользователь: "Какой материал указан на чертеже?"
```bash
curl -s --max-time 120 --connect-timeout 10 \
  -X POST http://api:8000/skills/blueprint-vision \
  -H "Content-Type: application/json" \
  -d "{\"image_path\": \"/app/documents/blueprints/чертеж.png\", \"question\": \"Какой материал и марка указаны на чертеже?\"}"
```

## Обработка ошибок

- `404`: Файл не найден — уточни у пользователя точное имя файла или попроси загрузить его в папку documents/blueprints/
- `415`: Неподдерживаемый формат — поддерживаются PNG, JPG, JPEG, WEBP
- `503`: Ошибка VLM — повтори запрос через 30 секунд

## Сценарий комплексного запроса (ТПА)

При запросе типа "У нас заказ по чертежу X, нужна пресс-форма":
1. Сначала вызови `blueprint-vision` → получи материал и деталь
2. Затем вызови `enterprise-graph-search` с информацией о детали → найди пресс-форму и ТПА
3. Затем вызови `inventory-sql-search` → проверь наличие полимера на складе
4. Объедини все результаты в сводный отчёт
