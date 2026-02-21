/**
 * Базовый HTTP-клиент.
 * Все запросы к FastAPI идут через nginx (/api/v1/...)
 * JWT-токен подставляется автоматически из localStorage.
 */

const BASE_URL = '/api/v1'

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function getToken(): string | null {
  return localStorage.getItem('access_token')
}

export function setToken(token: string): void {
  localStorage.setItem('access_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('current_user')
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const token = getToken()

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new ApiError(401, 'Сессия истекла')
  }

  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try {
      const errData = JSON.parse(text)
      detail = errData.detail ?? (typeof errData === 'string' ? errData : JSON.stringify(errData))
    } catch {
      /* оставляем detail = text */
    }
    throw new ApiError(res.status, `HTTP ${res.status}`, detail)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}

export const api = {
  get:    <T>(path: string) => request<T>('GET', path),
  post:   <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put:    <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch:  <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

export { ApiError }

/**
 * Загрузка файла через FormData (multipart/form-data).
 */
export async function uploadFile(
  folder: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<{ id: string; filename: string; message: string }> {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const formData = new FormData()
    formData.append('file', file)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE_URL}/files/upload/${folder}`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        let detail = xhr.responseText
        try {
          detail = JSON.parse(xhr.responseText)?.detail || detail
        } catch {}
        reject(new ApiError(xhr.status, `HTTP ${xhr.status}`, detail))
      }
    }

    xhr.onerror = () => reject(new Error('Ошибка сети при загрузке файла'))
    xhr.send(formData)
  })
}

/**
 * SSE подключение для стримингового чата.
 * Использует fetch + ReadableStream вместо EventSource (нужны кастомные заголовки).
 */
export async function* streamChat(
  sessionId: string,
  content: string,
): AsyncGenerator<Record<string, unknown>> {
  const token = getToken()

  const res = await fetch(`${BASE_URL}/chat/sessions/${sessionId}/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new ApiError(res.status, `Ошибка чата: HTTP ${res.status}`, text)
  }

  if (!res.body) throw new Error('Тело ответа недоступно')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('data: ')) {
          const jsonStr = trimmed.slice(6)
          if (jsonStr) {
            try {
              yield JSON.parse(jsonStr)
            } catch {
              // Пропускаем невалидные JSON-строки
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
