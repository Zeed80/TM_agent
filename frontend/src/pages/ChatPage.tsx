import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import {
  Plus, Send, Trash2, Edit2, Check, X,
  MessageSquare, Loader2, AlertCircle
} from 'lucide-react'
import { useChatStore } from '../store/chat'
import { streamChat, ApiError } from '../api/client'
import MessageBubble, { StreamingBubble } from '../components/chat/MessageBubble'
import clsx from 'clsx'

export default function ChatPage() {
  const {
    sessions, activeSessionId, messages, isStreaming,
    streamingText, statusText, activeTools,
    loadSessions, setActiveSession, loadMessages, createSession,
    deleteSession, renameSession, appendUserMessage, startStreaming,
    appendToken, setStatus, addActiveTool, removeActiveTool,
    finishStreaming, setStreamError,
  } = useChatStore()

  const [input, setInput] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoadingSessions, setIsLoadingSessions] = useState(true)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Загружаем сессии при монтировании
  useEffect(() => {
    loadSessions().finally(() => setIsLoadingSessions(false))
  }, [loadSessions])

  // Загружаем сообщения при смене сессии
  useEffect(() => {
    if (activeSessionId && !messages[activeSessionId]) {
      loadMessages(activeSessionId)
    }
  }, [activeSessionId, messages, loadMessages])

  // Скроллим вниз при новых сообщениях
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText, activeSessionId])

  // Авторесайз textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [input])

  const currentMessages = activeSessionId ? (messages[activeSessionId] ?? []) : []

  const handleNewChat = async () => {
    try {
      const session = await createSession()
      setActiveSession(session.id)
    } catch {
      setError('Не удалось создать чат')
    }
  }

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return
    if (!activeSessionId) {
      // Создаём сессию автоматически если нет активной
      try {
        const session = await createSession(input.slice(0, 40) + (input.length > 40 ? '...' : ''))
        setActiveSession(session.id)
        await _sendMessage(session.id, input.trim())
      } catch {
        setError('Не удалось создать чат')
      }
      return
    }
    await _sendMessage(activeSessionId, input.trim())
  }

  const _sendMessage = async (sessionId: string, content: string) => {
    setInput('')
    setError(null)
    appendUserMessage(sessionId, content)
    startStreaming()

    try {
      for await (const event of streamChat(sessionId, content)) {
        const ev = event as Record<string, unknown>
        switch (ev.type) {
          case 'status':
            setStatus(ev.text as string)
            break
          case 'tool_start':
            addActiveTool(ev.tool as string)
            break
          case 'tool_done':
            removeActiveTool(ev.tool as string)
            break
          case 'token':
            appendToken(ev.content as string)
            break
          case 'done':
            finishStreaming(ev.message_id as string, sessionId)
            break
          case 'error':
            setStreamError(ev.detail as string)
            setError(ev.detail as string)
            break
        }
      }
    } catch (err) {
      const detail = err instanceof ApiError ? (err.detail ?? err.message) : String(err)
      setStreamError(detail)
      setError(detail)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const startRename = (id: string, currentTitle: string) => {
    setEditingId(id)
    setEditTitle(currentTitle)
  }

  const confirmRename = async (id: string) => {
    if (editTitle.trim()) {
      await renameSession(id, editTitle.trim())
    }
    setEditingId(null)
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Список сессий (левая панель) ── */}
      <div className="w-56 shrink-0 flex flex-col bg-surface-900 border-r border-surface-700">
        <div className="p-3 border-b border-surface-700">
          <button
            onClick={handleNewChat}
            className="btn-primary w-full justify-center text-xs py-2"
          >
            <Plus size={14} />
            Новый чат
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {isLoadingSessions ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={18} className="animate-spin text-slate-500" />
            </div>
          ) : sessions.length === 0 ? (
            <p className="text-xs text-slate-600 text-center py-6 px-3">
              Нет чатов. Начните новый диалог.
            </p>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                className={clsx(
                  'group flex items-center gap-1 rounded-lg px-2 py-2 cursor-pointer transition-colors',
                  activeSessionId === session.id
                    ? 'bg-accent/15 text-slate-200'
                    : 'hover:bg-surface-800 text-slate-400 hover:text-slate-200',
                )}
                onClick={() => setActiveSession(session.id)}
              >
                <MessageSquare size={13} className="shrink-0 opacity-60" />

                {editingId === session.id ? (
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    <input
                      autoFocus
                      className="flex-1 min-w-0 bg-surface-700 border border-surface-600 rounded
                                 px-1.5 py-0.5 text-xs text-slate-100 focus:outline-none"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') confirmRename(session.id)
                        if (e.key === 'Escape') setEditingId(null)
                      }}
                    />
                    <button onClick={() => confirmRename(session.id)} className="text-green-400 hover:text-green-300">
                      <Check size={12} />
                    </button>
                    <button onClick={() => setEditingId(null)} className="text-slate-500 hover:text-slate-300">
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="flex-1 text-xs truncate">{session.title}</span>
                    <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                      <button
                        onClick={(e) => { e.stopPropagation(); startRename(session.id, session.title) }}
                        className="p-0.5 rounded text-slate-500 hover:text-slate-300"
                        title="Переименовать"
                      >
                        <Edit2 size={11} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); deleteSession(session.id) }}
                        className="p-0.5 rounded text-slate-500 hover:text-red-400"
                        title="Удалить"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Основная область чата ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeSessionId ? (
          <>
            {/* Заголовок */}
            <div className="shrink-0 px-4 py-3 border-b border-surface-700 flex items-center gap-3">
              <MessageSquare size={16} className="text-slate-500" />
              <h2 className="text-sm font-medium text-slate-200 truncate">
                {sessions.find((s) => s.id === activeSessionId)?.title ?? 'Чат'}
              </h2>
            </div>

            {/* Сообщения */}
            <div className="flex-1 overflow-y-auto py-4 space-y-1">
              {currentMessages
                .filter((m) => m.role !== 'tool')
                .map((msg) => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}

              {isStreaming && (
                <StreamingBubble
                  text={streamingText}
                  status={statusText}
                  activeTools={activeTools}
                />
              )}

              {error && (
                <div className="mx-4 flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                  <AlertCircle size={14} className="text-red-400 shrink-0" />
                  <p className="text-sm text-red-300">{error}</p>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Поле ввода */}
            <div className="shrink-0 p-4 border-t border-surface-700">
              <div className="flex items-end gap-3 bg-surface-800 border border-surface-700
                              rounded-2xl px-4 py-3 focus-within:border-accent/40 transition-colors">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Задайте вопрос... (Enter — отправить, Shift+Enter — перенос)"
                  disabled={isStreaming}
                  className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500
                             resize-none focus:outline-none leading-relaxed min-h-[24px] max-h-40"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isStreaming}
                  className={clsx(
                    'shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all',
                    input.trim() && !isStreaming
                      ? 'bg-accent text-white hover:bg-accent-hover'
                      : 'bg-surface-700 text-slate-500 cursor-not-allowed',
                  )}
                  title="Отправить (Enter)"
                >
                  {isStreaming
                    ? <Loader2 size={15} className="animate-spin" />
                    : <Send size={15} />
                  }
                </button>
              </div>
              <p className="text-xs text-slate-600 mt-1.5 text-center">
                Ярослав может ошибаться. Проверяйте важные данные.
              </p>
            </div>
          </>
        ) : (
          /* Пустое состояние */
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
            <div className="w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center mb-4">
              <MessageSquare size={28} className="text-accent-light" />
            </div>
            <h3 className="text-lg font-semibold text-slate-200 mb-2">Начните диалог</h3>
            <p className="text-sm text-slate-500 max-w-xs mb-6">
              Задайте вопрос о производстве, документации, складе или загрузите чертёж для анализа.
            </p>
            <button onClick={handleNewChat} className="btn-primary">
              <Plus size={16} />
              Новый чат
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
