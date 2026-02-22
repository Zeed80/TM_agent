import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Loader2, AlertCircle } from 'lucide-react'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'

type SettingsMap = Record<string, string | number | boolean | null>

const SECTIONS: { title: string; keys: { key: keyof SettingsMap; label: string; type: 'text' | 'number' | 'boolean'; placeholder?: string }[] }[] = [
  {
    title: 'Модели (Ollama)',
    keys: [
      { key: 'llm_model', label: 'LLM модель', type: 'text', placeholder: 'qwen3:30b' },
      { key: 'vlm_model', label: 'VLM модель', type: 'text', placeholder: 'qwen3-vl:14b' },
      { key: 'embedding_model', label: 'Embedding модель', type: 'text', placeholder: 'qwen3-embedding' },
      { key: 'reranker_model', label: 'Reranker модель', type: 'text', placeholder: 'qwen3-reranker' },
    ],
  },
  {
    title: 'Ollama URL',
    keys: [
      { key: 'ollama_gpu_url', label: 'Ollama GPU URL', type: 'text', placeholder: 'http://ollama-gpu:11434' },
      { key: 'ollama_cpu_url', label: 'Ollama CPU URL', type: 'text', placeholder: 'http://ollama-cpu:11434' },
    ],
  },
  {
    title: 'Контекст и таймауты',
    keys: [
      { key: 'llm_num_ctx', label: 'LLM размер контекста', type: 'number' },
      { key: 'vlm_num_ctx', label: 'VLM размер контекста', type: 'number' },
      { key: 'llm_timeout', label: 'LLM таймаут (с)', type: 'number' },
      { key: 'vlm_timeout', label: 'VLM таймаут (с)', type: 'number' },
      { key: 'embedding_timeout', label: 'Embedding таймаут (с)', type: 'number' },
      { key: 'reranker_timeout', label: 'Reranker таймаут (с)', type: 'number' },
      { key: 'vram_swap_timeout', label: 'VRAM переключение (с)', type: 'number' },
    ],
  },
  {
    title: 'Qdrant',
    keys: [
      { key: 'qdrant_collection', label: 'Коллекция', type: 'text', placeholder: 'documents' },
      { key: 'embedding_dim', label: 'Размерность вектора', type: 'number' },
      { key: 'qdrant_dense_vector_name', label: 'Имя dense-вектора', type: 'text' },
      { key: 'qdrant_sparse_vector_name', label: 'Имя sparse-вектора', type: 'text' },
      { key: 'qdrant_prefetch_limit', label: 'Prefetch limit', type: 'number' },
      { key: 'qdrant_final_limit', label: 'Финальный limit', type: 'number' },
    ],
  },
  {
    title: 'Чат и агент',
    keys: [
      { key: 'chat_max_tool_iterations', label: 'Макс. итераций инструментов', type: 'number' },
    ],
  },
  {
    title: 'Облачные провайдеры',
    keys: [
      { key: 'cloud_llm_timeout', label: 'Облачный LLM таймаут (с)', type: 'number' },
      { key: 'cloud_embedding_timeout', label: 'Облачный Embedding таймаут (с)', type: 'number' },
      { key: 'openrouter_base_url', label: 'OpenRouter Base URL', type: 'text' },
      { key: 'vllm_base_url', label: 'vLLM Base URL (или пусто)', type: 'text', placeholder: 'http://vllm:8000/v1' },
    ],
  },
  {
    title: 'OpenClaw (Telegram-агент)',
    keys: [
      { key: 'openclaw_llm_model', label: 'Модель LLM для OpenClaw', type: 'text', placeholder: 'как llm_model' },
      { key: 'openclaw_auto_update', label: 'Автообновление OpenClaw при рестарте', type: 'boolean' },
    ],
  },
  {
    title: 'Прочее',
    keys: [
      { key: 'documents_base_dir', label: 'Директория документов', type: 'text' },
      { key: 'cors_origins', label: 'CORS origins (через запятую)', type: 'text', placeholder: '*' },
    ],
  },
]

export default function SettingsPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const queryClient = useQueryClient()
  const [form, setForm] = useState<SettingsMap>({})
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const { data: settings, isLoading } = useQuery<SettingsMap>({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingsMap>('/settings'),
    enabled: isAdmin,
  })

  useEffect(() => {
    if (settings && typeof settings === 'object') {
      setForm({ ...settings })
    }
  }, [settings])

  const patchSettings = useMutation({
    mutationFn: async (body: SettingsMap) => {
      await api.patch('/settings', body)
    },
    onSuccess: () => {
      setMessage({ type: 'ok', text: 'Настройки сохранены.' })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setTimeout(() => setMessage(null), 4000)
    },
    onError: (err: Error) => {
      setMessage({ type: 'err', text: err.message || 'Ошибка сохранения' })
    },
  })

  const handleChange = (key: string, value: string | number | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setMessage(null)
    patchSettings.mutate(form)
  }

  if (!isAdmin) {
    return (
      <div className="p-6">
        <p className="text-slate-500">Доступ только для администратора.</p>
      </div>
    )
  }

  if (isLoading || !form || Object.keys(form).length === 0) {
    return (
      <div className="p-6 flex items-center gap-2 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span>Загрузка настроек...</span>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-semibold text-slate-100 mb-2">Настройки системы</h1>
      <p className="text-sm text-slate-500 mb-6">
        Значения из этой страницы имеют приоритет над .env. Пароли БД и JWT задаются только в .env.
      </p>

      {message && (
        <div
          className={message.type === 'ok'
            ? 'mb-4 p-3 rounded-lg bg-green-500/10 border border-green-500/30 text-green-300 text-sm'
            : 'mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-center gap-2'}
        >
          {message.type === 'err' && <AlertCircle size={18} />}
          {message.text}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-8">
        {SECTIONS.map((section) => (
          <section key={section.title} className="card p-5">
            <h2 className="text-sm font-semibold text-slate-300 mb-4 border-b border-surface-700 pb-2">
              {section.title}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {section.keys.map(({ key, label, type, placeholder }) => {
                const value = form[key]
                if (type === 'boolean') {
                  return (
                    <div key={key} className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        id={key}
                        checked={value === true}
                        onChange={(e) => handleChange(key, e.target.checked)}
                        className="rounded border-surface-600 bg-surface-800 text-brand-500 focus:ring-brand-500"
                      />
                      <label htmlFor={key} className="text-sm text-slate-300">
                        {label}
                      </label>
                    </div>
                  )
                }
                return (
                  <div key={key}>
                    <label htmlFor={key} className="block text-xs text-slate-500 mb-1">
                      {label}
                    </label>
                    <input
                      id={key}
                      type={type}
                      value={value == null ? '' : String(value)}
                      onChange={(e) =>
                        handleChange(
                          key,
                          type === 'number' ? (e.target.value === '' ? 0 : Number(e.target.value)) : e.target.value
                        )
                      }
                      placeholder={placeholder}
                      className="w-full px-3 py-2 rounded-lg bg-surface-800 border border-surface-600 text-slate-200 placeholder:text-slate-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 text-sm"
                    />
                  </div>
                )
              })}
            </div>
          </section>
        ))}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={patchSettings.isPending}
            className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white font-medium flex items-center gap-2 disabled:opacity-50"
          >
            {patchSettings.isPending ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Save size={18} />
            )}
            Сохранить настройки
          </button>
        </div>
      </form>
    </div>
  )
}
