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
  | 'invoices'
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
  files_with_errors?: Array<{
    id: string
    filename: string
    folder: string
    status: 'uploaded' | 'processing' | 'indexed' | 'error'
    error_msg: string | null
    created_at: string
    indexed_at: string | null
  }>
}

// ─── Models (реестр провайдеров и назначений) ────────────────────────
export interface ProviderInfo {
  id: string
  type: string
  name: string
  config: Record<string, unknown>
  api_key_set: boolean
  models: string[]
}

export interface AssignmentItem {
  role: string
  provider_id: string
  provider_type: string
  model_id: string
  is_cloud: boolean
}

export interface AssignmentsResponse {
  llm: AssignmentItem
  vlm: AssignmentItem
  embedding: AssignmentItem
  reranker: AssignmentItem
}

export interface OllamaInstanceModels {
  instance: string
  url: string
  models: string[]
}
