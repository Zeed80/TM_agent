// ─── Auth ──────────────────────────────────────────────────────────────
export interface User {
  id: string
  username: string
  full_name: string | null
  email: string | null
  role: 'admin' | 'user'
  is_active: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

// ─── Chat ──────────────────────────────────────────────────────────────
export interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export type MessageRole = 'user' | 'assistant' | 'tool'

export interface ChatMessage {
  id: string
  session_id: string
  role: MessageRole
  content: string
  tool_name: string | null
  tool_input: Record<string, unknown> | null
  tool_result: Record<string, unknown> | null
  created_at: string
}

// SSE Events от сервера
export type SSEEventType =
  | { type: 'status';     text: string }
  | { type: 'tool_start'; tool: string; input: Record<string, unknown> }
  | { type: 'tool_done';  tool: string; summary: string }
  | { type: 'token';      content: string }
  | { type: 'done';       message_id: string }
  | { type: 'error';      detail: string }

// ─── Files ─────────────────────────────────────────────────────────────
export type DocumentFolder =
  | 'blueprints'
  | 'manuals'
  | 'gosts'
  | 'emails'
  | 'catalogs'
  | 'tech_processes'

export interface UploadedFile {
  id: string
  filename: string
  folder: DocumentFolder
  file_size: number | null
  mime_type: string | null
  status: 'uploaded' | 'processing' | 'indexed' | 'error'
  error_msg: string | null
  created_at: string
}

// ─── System Status ─────────────────────────────────────────────────────
export interface ServiceStatus {
  name: string
  status: 'ok' | 'error' | 'unknown'
  detail: string | null
  latency_ms: number | null
}

export interface SystemStatus {
  services: ServiceStatus[]
  vram: {
    current_model: string | null
    gpu_available: boolean
  }
  disk_usage: Array<{
    folder: string
    files_count: number
    total_size_mb: number
  }>
  llm_model: string
  vlm_model: string
  embedding_model: string
  reranker_model: string
}
