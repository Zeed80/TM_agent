"""
Роутер чат-сессий с SSE-стримингом и Agentic Loop.

Архитектура чата:
  1. Пользователь отправляет сообщение (POST /sessions/{id}/message)
  2. FastAPI создаёт SSE-поток
  3. История из PostgreSQL → Ollama /api/chat с tools
  4. Если LLM вызывает инструмент → выполняем навык → добавляем результат → повтор
  5. Финальный ответ стримится токенами клиенту
  6. Все сообщения сохраняются в PostgreSQL

SSE Events (media_type="text/event-stream"):
  data: {"type": "status",     "text": "..."}
  data: {"type": "tool_start", "tool": "graph_search", "input": {...}}
  data: {"type": "tool_done",  "tool": "graph_search", "summary": "Найдено N записей"}
  data: {"type": "token",      "content": "фрагмент текста"}
  data: {"type": "done",       "message_id": "uuid"}
  data: {"type": "error",      "detail": "..."}
"""

import json
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.ai_engine.model_assignments import get_assignment
from src.ai_engine.vram_manager import VRAMManager
from src.app_settings import get_setting
from src.auth import get_current_user
from src.db.postgres_client import postgres_client as _pg
from src.models.chat_models import (
    ChatMessagePublic,
    CreateSessionRequest,
    SendMessageRequest,
    SessionPublic,
    UpdateSessionRequest,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)

# ── Определения инструментов для Ollama tools API ──────────────────────
_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "enterprise_graph_search",
            "description": (
                "Поиск по производственному графу знаний. "
                "Используй для вопросов о: деталях и их чертежах, маршрутах изготовления, "
                "техпроцессах и операциях, станках и оборудовании, пресс-формах и оснастке, "
                "связях между деталями и операциями."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Вопрос о производственных данных на русском языке",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enterprise_docs_search",
            "description": (
                "Поиск в технической документации завода (Hybrid Search: BM25 + семантический). "
                "Используй для вопросов о: ГОСТах и стандартах, паспортах оборудования, "
                "инструкциях по эксплуатации, деловой переписке, регламентах."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Вопрос для поиска в документах на русском языке",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_sql_search",
            "description": (
                "Запросы к складской базе данных (PostgreSQL). "
                "Используй для вопросов об: остатках инструмента, металлов, полимеров на складе, "
                "каталогах номенклатуры, характеристиках материалов и режущего инструмента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Вопрос о складе или номенклатуре на русском языке",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "blueprint_vision",
            "description": (
                "Анализ чертежа через мультимодальную модель (VLM). "
                "Используй когда пользователь загрузил чертёж и хочет узнать: "
                "номер чертежа, размеры, допуски, шероховатость, материал, обозначения."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Путь к файлу чертежа (например: /app/documents/blueprints/detail.png)",
                    },
                    "question": {
                        "type": "string",
                        "description": "Что нужно определить на чертеже",
                    },
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "norm_control",
            "description": (
                "Проверка чертежа или техпроцесса на соответствие нормам и ГОСТам (нормоконтроль). "
                "Используй, когда пользователь просит провести нормоконтроль, проверить оформление документа или соответствие стандартам."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_type": {
                        "type": "string",
                        "enum": ["drawing", "tech_process"],
                        "description": "Тип документа: drawing — чертёж, tech_process — техпроцесс",
                    },
                    "identifier": {
                        "type": "string",
                        "description": "Номер чертежа или номер техпроцесса (например ТП-001)",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Путь к файлу чертежа (опционально, только для drawing)",
                    },
                },
                "required": ["document_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Поиск в интернете. Используй для актуальной информации из веба: новости, курсы валют, "
                "документация производителей, стандарты, погода и т.п."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском или английском",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

# Системный промпт для Web-чата
_SYSTEM_PROMPT = """Ты — Ярослав, ИТР-ассистент производственного предприятия.
Ты общаешься через защищённый веб-интерфейс с инженерно-техническими работниками (ИТР) завода.

ПРАВИЛА РАБОТЫ:
1. Всегда используй инструменты для получения актуальных данных из баз завода. Не придумывай факты.
2. Если данные получены — ссылайся на источник (название инструмента, откуда данные).
3. Для сложных запросов вызывай несколько инструментов последовательно.
4. Отвечай структурированно: заголовки, списки, таблицы в Markdown.
5. Если инструмент вернул ошибку — сообщи пользователю и предложи альтернативу.
6. Общайся на русском языке. Технические термины используй точно.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
- enterprise_graph_search: производственный граф (детали, маршруты, техпроцессы, станки, трудозатраты)
- enterprise_docs_search: техдокументация (ГОСТы, паспорта, инструкции)
- inventory_sql_search: складской учёт (остатки, номенклатура)
- blueprint_vision: анализ чертежей (требует путь к файлу)
- norm_control: нормоконтроль чертежа или техпроцесса (document_type + identifier или image_path)
- web_search: поиск в интернете (актуальная информация из веба)
"""

# Timeout для внутренних вызовов инструментов (те же 120s, правило 1)
_TOOL_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=5.0)


# ─────────────────────────────────────────────────────────────────────
# CRUD сессий
# ─────────────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=SessionPublic, status_code=201)
async def create_session(
    request: CreateSessionRequest,
    current_user: dict = Depends(get_current_user),
) -> SessionPublic:
    """Создать новую чат-сессию."""
    rows = await _pg.execute_query(
        "INSERT INTO chat_sessions (user_id, title) VALUES (:uid, :title) "
        "RETURNING id, title, created_at, updated_at",
        {"uid": str(current_user["id"]), "title": request.title},
    )
    session = dict(rows[0])
    session["message_count"] = 0
    return SessionPublic(**session)


@router.get("/sessions", response_model=list[SessionPublic])
async def list_sessions(
    current_user: dict = Depends(get_current_user),
) -> list[SessionPublic]:
    """Список сессий текущего пользователя (от новой к старой)."""
    rows = await _pg.execute_query(
        """
        SELECT s.id, s.title, s.created_at, s.updated_at,
               COUNT(m.id) AS message_count
        FROM chat_sessions s
        LEFT JOIN chat_messages m ON m.session_id = s.id
        WHERE s.user_id = :uid
        GROUP BY s.id
        ORDER BY s.updated_at DESC
        """,
        {"uid": str(current_user["id"])},
    )
    return [SessionPublic(**dict(row)) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionPublic)
async def get_session(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
) -> SessionPublic:
    """Получить сессию по ID."""
    rows = await _pg.execute_query(
        """
        SELECT s.id, s.title, s.created_at, s.updated_at,
               COUNT(m.id) AS message_count
        FROM chat_sessions s
        LEFT JOIN chat_messages m ON m.session_id = s.id
        WHERE s.id = :sid AND s.user_id = :uid
        GROUP BY s.id
        """,
        {"sid": str(session_id), "uid": str(current_user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Сессия не найдена.")
    return SessionPublic(**dict(rows[0]))


@router.patch("/sessions/{session_id}", response_model=SessionPublic)
async def update_session(
    session_id: UUID,
    request: UpdateSessionRequest,
    current_user: dict = Depends(get_current_user),
) -> SessionPublic:
    """Переименовать сессию."""
    rows = await _pg.execute_query(
        "UPDATE chat_sessions SET title = :title, updated_at = NOW() "
        "WHERE id = :sid AND user_id = :uid "
        "RETURNING id, title, created_at, updated_at",
        {"title": request.title, "sid": str(session_id), "uid": str(current_user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Сессия не найдена.")
    session = dict(rows[0])
    session["message_count"] = 0
    return SessionPublic(**session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
) -> None:
    """Удалить сессию со всеми сообщениями."""
    rows = await _pg.execute_query(
        "DELETE FROM chat_sessions WHERE id = :sid AND user_id = :uid RETURNING id",
        {"sid": str(session_id), "uid": str(current_user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Сессия не найдена.")


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessagePublic])
async def get_messages(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
) -> list[ChatMessagePublic]:
    """Получить все сообщения сессии."""
    # Проверяем принадлежность сессии
    sessions = await _pg.execute_query(
        "SELECT id FROM chat_sessions WHERE id = :sid AND user_id = :uid",
        {"sid": str(session_id), "uid": str(current_user["id"])},
    )
    if not sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена.")

    rows = await _pg.execute_query(
        "SELECT id, session_id, role, content, tool_name, tool_input, tool_result, created_at "
        "FROM chat_messages WHERE session_id = :sid ORDER BY created_at ASC",
        {"sid": str(session_id)},
    )
    return [ChatMessagePublic(**dict(row)) for row in rows]


# ─────────────────────────────────────────────────────────────────────
# SSE Chat endpoint — основной
# ─────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: UUID,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """
    Отправить сообщение и получить ответ ассистента через SSE-стриминг.

    Клиент подключается как EventSource и получает события:
      {"type": "status", "text": "..."}
      {"type": "tool_start", "tool": "...", "input": {...}}
      {"type": "tool_done",  "tool": "...", "summary": "..."}
      {"type": "token",      "content": "..."}
      {"type": "done",       "message_id": "..."}
    """
    # Проверяем принадлежность сессии
    sessions = await _pg.execute_query(
        "SELECT id FROM chat_sessions WHERE id = :sid AND user_id = :uid",
        {"sid": str(session_id), "uid": str(current_user["id"])},
    )
    if not sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена.")

    return StreamingResponse(
        _stream_agent_response(session_id, request.content, current_user, request.images),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Отключаем буферизацию nginx
            "Connection": "keep-alive",
        },
    )


async def _stream_agent_response(
    session_id: UUID,
    user_content: str,
    current_user: dict,
    user_images: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Генератор SSE-событий для одного сообщения пользователя.
    Реализует agentic loop: LLM → Tool → LLM → ... → Stream response.
    """
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    try:
        # ── Сохранить сообщение пользователя ─────────────────────────
        await _pg.execute_query(
            "INSERT INTO chat_messages (id, session_id, role, content) "
            "VALUES (:id, :sid, 'user', :content)",
            {"id": user_msg_id, "sid": str(session_id), "content": user_content},
        )
        # Обновляем updated_at сессии
        await _pg.execute_query(
            "UPDATE chat_sessions SET updated_at = NOW() WHERE id = :sid",
            {"sid": str(session_id)},
        )

        yield _sse({"type": "status", "text": "Анализирую запрос..."})

        # ── Загрузить историю сообщений для контекста ─────────────────
        history_rows = await _pg.execute_query(
            """
            SELECT role, content, tool_name, tool_input, tool_result
            FROM chat_messages
            WHERE session_id = :sid
            ORDER BY created_at ASC
            """,
            {"sid": str(session_id)},
        )

        # Собираем messages для Ollama (только user/assistant/tool)
        ollama_messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT}
        ]
        for row in history_rows:
            r = dict(row)
            if r["role"] == "user":
                ollama_messages.append({"role": "user", "content": r["content"]})
            elif r["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": r["content"] or ""}
                ollama_messages.append(msg)
            elif r["role"] == "tool" and r["tool_name"]:
                # Результат инструмента добавляем как отдельное сообщение
                tool_result_str = json.dumps(r["tool_result"], ensure_ascii=False) \
                    if isinstance(r["tool_result"], dict) else str(r["tool_result"] or "")
                ollama_messages.append({"role": "tool", "content": tool_result_str})

        # Текущее сообщение пользователя (с опциональными изображениями для мультимодального чата)
        current_user_msg: dict = {"role": "user", "content": user_content}
        if user_images:
            current_user_msg["images"] = user_images[:5]  # не более 5 изображений
        ollama_messages.append(current_user_msg)

        # ── Текущее назначение LLM (из реестра или env) ───────────────
        llm_assignment = await get_assignment("llm")
        ollama_url = (llm_assignment.get("config") or {}).get("url", "").strip() or get_setting("ollama_gpu_url")
        llm_model = (llm_assignment.get("model_id") or "").strip() or get_setting("llm_model")
        provider_type = (llm_assignment.get("provider_type") or "").strip().lower()

        # ── Agentic Loop ──────────────────────────────────────────────
        vram = VRAMManager()
        if provider_type == "ollama_gpu":
            await vram.ensure_llm_for_model(llm_model)
        else:
            await vram.ensure_llm()

        full_assistant_content = ""
        tool_messages_to_save: list[dict] = []

        for iteration in range(get_setting("chat_max_tool_iterations")):
            yield _sse({"type": "status", "text": f"Мышление {'.' * (iteration + 1)}"})

            # Вызов Ollama: НЕ стримим (ждём tool_calls)
            async with httpx.AsyncClient(timeout=_TOOL_TIMEOUT) as client:
                resp = await client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": llm_model,
                        "messages": ollama_messages,
                        "tools": _TOOLS,
                        "stream": False,
                        "options": {
                            "num_ctx": get_setting("llm_num_ctx"),
                            "temperature": 0.7,
                            "repeat_penalty": 1.1,
                        },
                    },
                )
                resp.raise_for_status()
                ollama_data = resp.json()

            message = ollama_data.get("message", {})
            tool_calls = message.get("tool_calls", [])

            if not tool_calls:
                # Финальный ответ — теперь стримим через Ollama streaming
                final_text = message.get("content", "")
                if final_text:
                    # Разбиваем на токены (уже получен полный ответ, имитируем стриминг)
                    full_assistant_content = final_text
                    # Стримим ответ кусочками для лучшего UX
                    chunk_size = 8
                    for i in range(0, len(final_text), chunk_size):
                        chunk = final_text[i:i + chunk_size]
                        yield _sse({"type": "token", "content": chunk})
                break

            # ── Обрабатываем вызовы инструментов ─────────────────────
            # Добавляем assistant message с tool_calls в ollama_messages
            ollama_messages.append({
                "role": "assistant",
                "content": message.get("content", ""),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                tool_args = fn.get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {}

                yield _sse({"type": "tool_start", "tool": tool_name, "input": tool_args})

                # Выполнить инструмент
                tool_result_str, summary = await _execute_tool(tool_name, tool_args)

                yield _sse({"type": "tool_done", "tool": tool_name, "summary": summary})

                # Добавляем результат в ollama_messages
                ollama_messages.append({
                    "role": "tool",
                    "content": tool_result_str,
                })

                # Сохраним информацию для записи в БД
                tool_messages_to_save.append({
                    "tool_name": tool_name,
                    "tool_input": tool_args,
                    "tool_result_str": tool_result_str,
                })

        else:
            # Превышен лимит итераций
            fallback = "Достигнут предел вызовов инструментов. Попробуйте переформулировать запрос."
            full_assistant_content = fallback
            yield _sse({"type": "token", "content": fallback})

        # ── Сохранить tool-сообщения в БД ────────────────────────────
        for tm in tool_messages_to_save:
            try:
                result_dict: dict | None = None
                try:
                    result_dict = json.loads(tm["tool_result_str"])
                    if not isinstance(result_dict, dict):
                        result_dict = {"raw": result_dict}
                except json.JSONDecodeError:
                    result_dict = {"raw": tm["tool_result_str"]}

                await _pg.execute_query(
                    "INSERT INTO chat_messages (session_id, role, content, tool_name, tool_input, tool_result) "
                    "VALUES (:sid, 'tool', :content, :tool_name, :tool_input, :tool_result)",
                    {
                        "sid": str(session_id),
                        "content": tm["tool_result_str"][:2000],
                        "tool_name": tm["tool_name"],
                        "tool_input": json.dumps(tm["tool_input"], ensure_ascii=False),
                        "tool_result": json.dumps(result_dict, ensure_ascii=False),
                    },
                )
            except Exception as exc:
                logger.warning(f"[Chat] Не удалось сохранить tool-сообщение: {exc}")

        # ── Сохранить ответ ассистента в БД ──────────────────────────
        await _pg.execute_query(
            "INSERT INTO chat_messages (id, session_id, role, content) "
            "VALUES (:id, :sid, 'assistant', :content)",
            {
                "id": assistant_msg_id,
                "sid": str(session_id),
                "content": full_assistant_content,
            },
        )
        await _pg.execute_query(
            "UPDATE chat_sessions SET updated_at = NOW() WHERE id = :sid",
            {"sid": str(session_id)},
        )

        yield _sse({"type": "done", "message_id": assistant_msg_id})

    except Exception as exc:
        logger.error(f"[Chat] Ошибка в stream: {exc}", exc_info=True)
        yield _sse({"type": "error", "detail": str(exc)})


# ─────────────────────────────────────────────────────────────────────
# Tool Executor — вызывает внутренние навыки через HTTP
# ─────────────────────────────────────────────────────────────────────

async def _execute_tool(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """
    Выполняет инструмент, вызывая соответствующий навык через HTTP.
    Возвращает (результат_str, краткое_резюме).
    """
    # Маршрутизация инструментов → внутренние endpoints
    # Веб-поиск — через Serper API (если задан web_search_api_key в Настройках)
    if tool_name == "web_search":
        return await _execute_web_search(tool_input)

    endpoint_map = {
        "enterprise_graph_search": "/skills/graph-search",
        "enterprise_docs_search":  "/skills/docs-search",
        "inventory_sql_search":    "/skills/inventory-sql",
        "blueprint_vision":        "/skills/blueprint-vision",
        "norm_control":            "/skills/norm-control",
    }

    endpoint = endpoint_map.get(tool_name)
    if not endpoint:
        result = {"error": f"Неизвестный инструмент: {tool_name}"}
        return json.dumps(result, ensure_ascii=False), "Ошибка: неизвестный инструмент"

    # Формируем тело запроса в зависимости от инструмента
    if tool_name == "enterprise_graph_search":
        body = {"question": tool_input.get("question", "")}
    elif tool_name == "enterprise_docs_search":
        body = {"question": tool_input.get("question", "")}
    elif tool_name == "inventory_sql_search":
        body = {"question": tool_input.get("question", "")}
    elif tool_name == "blueprint_vision":
        body = {
            "image_path": tool_input.get("image_path", ""),
            "question": tool_input.get("question", "Проведи полный анализ чертежа"),
        }
    elif tool_name == "norm_control":
        body = {
            "document_type": tool_input.get("document_type", "drawing"),
            "identifier": tool_input.get("identifier", ""),
            "image_path": tool_input.get("image_path") or None,
        }
    else:
        body = tool_input

    try:
        async with httpx.AsyncClient(
            base_url="http://localhost:8000",
            timeout=_TOOL_TIMEOUT,
        ) as client:
            resp = await client.post(
                endpoint,
                json=body,
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code == 200:
            data = resp.json()
            result_str = json.dumps(data, ensure_ascii=False)

            # Формируем краткое резюме
            if tool_name == "enterprise_graph_search":
                count = data.get("records_count", 0)
                summary = f"Найдено {count} записей в производственном графе"
            elif tool_name == "enterprise_docs_search":
                count = data.get("chunks_found", len(data.get("sources", [])))
                summary = f"Найдено {count} фрагментов документации"
            elif tool_name == "inventory_sql_search":
                count = data.get("rows_count", 0)
                summary = f"Получено {count} записей из склада"
            elif tool_name == "blueprint_vision":
                summary = "Чертёж проанализирован"
            elif tool_name == "norm_control":
                summary = (
                    "Нормоконтроль пройден" if data.get("passed") else "Нормоконтроль не пройден"
                )
            else:
                summary = "Выполнено"

            return result_str, summary
        else:
            error = {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]}
            return json.dumps(error, ensure_ascii=False), f"Ошибка {resp.status_code}"

    except httpx.TimeoutException:
        error = {"error": "Timeout", "detail": f"Инструмент {tool_name} не ответил за 120 секунд"}
        return json.dumps(error, ensure_ascii=False), "Таймаут инструмента"
    except Exception as exc:
        logger.error(f"[Chat] Ошибка вызова инструмента {tool_name}: {exc}")
        error = {"error": str(exc)}
        return json.dumps(error, ensure_ascii=False), f"Ошибка: {exc}"


async def _execute_web_search(tool_input: dict) -> tuple[str, str]:
    """Веб-поиск через Serper API (google.serper.dev). Ключ задаётся в Настройках: web_search_api_key."""
    api_key = (get_setting("web_search_api_key") or "").strip()
    query = (tool_input.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "Пустой запрос"}, ensure_ascii=False), "Пустой запрос"

    if not api_key:
        return (
            json.dumps(
                {
                    "info": "Веб-поиск не настроен. Задайте web_search_api_key в Настройках (Serper API: serper.dev) или откройте OpenClaw для веб-поиска.",
                },
                ensure_ascii=False,
            ),
            "Веб-поиск не настроен",
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 8},
            )
            resp.raise_for_status()
            data = resp.json()

        organic = data.get("organic", [])[:8]
        snippets = [
            {"title": o.get("title", ""), "snippet": o.get("snippet", ""), "link": o.get("link", "")}
            for o in organic
        ]
        result = {"query": query, "results": snippets}
        summary = f"Найдено {len(snippets)} результатов по запросу «{query[:50]}»"
        return json.dumps(result, ensure_ascii=False), summary
    except httpx.HTTPStatusError as e:
        error = {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:300]}
        return json.dumps(error, ensure_ascii=False), f"Ошибка веб-поиска: {e.response.status_code}"
    except Exception as exc:
        logger.warning(f"[Chat] Веб-поиск: {exc}")
        return (
            json.dumps({"error": str(exc)}, ensure_ascii=False),
            f"Ошибка: {exc}",
        )


def _sse(data: dict) -> str:
    """Формирует SSE-событие."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
