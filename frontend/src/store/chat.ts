import { create } from 'zustand'
import type { ChatMessage, ChatSession } from '../types'
import { api } from '../api/client'

interface ChatStore {
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: Record<string, ChatMessage[]>
  isStreaming: boolean
  streamingText: string
  statusText: string
  activeTools: string[]

  loadSessions: () => Promise<void>
  setActiveSession: (id: string) => void
  loadMessages: (sessionId: string) => Promise<void>
  createSession: (title?: string) => Promise<ChatSession>
  deleteSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>

  appendUserMessage: (sessionId: string, content: string) => void
  startStreaming: () => void
  appendToken: (token: string) => void
  setStatus: (text: string) => void
  addActiveTool: (tool: string) => void
  removeActiveTool: (tool: string) => void
  finishStreaming: (messageId: string, sessionId: string) => void
  setStreamError: (detail: string) => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  isStreaming: false,
  streamingText: '',
  statusText: '',
  activeTools: [],

  loadSessions: async () => {
    const sessions = await api.get<ChatSession[]>('/chat/sessions')
    set({ sessions })
  },

  setActiveSession: (id) => {
    set({ activeSessionId: id, streamingText: '', statusText: '', activeTools: [] })
  },

  loadMessages: async (sessionId) => {
    const messages = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
    set((s) => ({ messages: { ...s.messages, [sessionId]: messages } }))
  },

  createSession: async (title = 'Новый чат') => {
    const session = await api.post<ChatSession>('/chat/sessions', { title })
    set((s) => ({ sessions: [session, ...s.sessions] }))
    return session
  },

  deleteSession: async (id) => {
    await api.delete(`/chat/sessions/${id}`)
    set((s) => {
      const sessions = s.sessions.filter((ss) => ss.id !== id)
      const messages = { ...s.messages }
      delete messages[id]
      const activeSessionId = s.activeSessionId === id
        ? (sessions[0]?.id ?? null)
        : s.activeSessionId
      return { sessions, messages, activeSessionId }
    })
  },

  renameSession: async (id, title) => {
    const updated = await api.patch<ChatSession>(`/chat/sessions/${id}`, { title })
    set((s) => ({
      sessions: s.sessions.map((ss) => (ss.id === id ? updated : ss)),
    }))
  },

  appendUserMessage: (sessionId, content) => {
    const msg: ChatMessage = {
      id: `tmp-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      tool_name: null,
      tool_input: null,
      tool_result: null,
      created_at: new Date().toISOString(),
    }
    set((s) => ({
      messages: {
        ...s.messages,
        [sessionId]: [...(s.messages[sessionId] ?? []), msg],
      },
    }))
  },

  startStreaming: () => {
    set({ isStreaming: true, streamingText: '', statusText: '', activeTools: [] })
  },

  appendToken: (token) => {
    set((s) => ({ streamingText: s.streamingText + token }))
  },

  setStatus: (text) => {
    set({ statusText: text })
  },

  addActiveTool: (tool) => {
    set((s) => ({ activeTools: [...s.activeTools, tool] }))
  },

  removeActiveTool: (tool) => {
    set((s) => ({ activeTools: s.activeTools.filter((t) => t !== tool) }))
  },

  finishStreaming: (messageId, sessionId) => {
    const { streamingText } = get()
    const msg: ChatMessage = {
      id: messageId,
      session_id: sessionId,
      role: 'assistant',
      content: streamingText,
      tool_name: null,
      tool_input: null,
      tool_result: null,
      created_at: new Date().toISOString(),
    }
    set((s) => ({
      isStreaming: false,
      streamingText: '',
      statusText: '',
      activeTools: [],
      messages: {
        ...s.messages,
        [sessionId]: [...(s.messages[sessionId] ?? []), msg],
      },
      // Обновляем updated_at сессии
      sessions: s.sessions.map((ss) =>
        ss.id === sessionId
          ? { ...ss, updated_at: new Date().toISOString(), message_count: ss.message_count + 2 }
          : ss,
      ),
    }))
  },

  setStreamError: (detail) => {
    set({ isStreaming: false, streamingText: '', statusText: '', activeTools: [] })
  },
}))
