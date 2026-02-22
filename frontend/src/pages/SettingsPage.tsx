import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Loader2, AlertCircle, Cpu, Database, Bot, MessageSquare, Settings2, Key, Copy, ExternalLink } from 'lucide-react'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'
import { LocalModelsTab, AssignmentsBlock, CloudModelsTab } from './ModelsPage'
import clsx from 'clsx'

type SettingsMap = Record<string, string | number | boolean | null>

type SectionDef = {
  title: string
  keys: { key: keyof SettingsMap; label: string; type: 'text' | 'number' | 'boolean'; placeholder?: string }[]
}

const SECTIONS: SectionDef[] = [
  {
    title: 'Модели (Ollama) — имена по умолчанию',
    keys: [
      { key: 'llm_model', label: 'LLM модель (по умолчанию)', type: 'text', placeholder: 'qwen3:30b' },
      { key: 'vlm_model', label: 'VLM модель (по умолчанию)', type: 'text', placeholder: 'qwen3-vl:14b' },
      { key: 'embedding_model', label: 'Embedding модель (по умолчанию)', type: 'text', placeholder: 'qwen3-embedding' },
      { key: 'reranker_model', label: 'Reranker модель (по умолчанию)', type: 'text', placeholder: 'qwen3-reranker' },
    ],
  },
  {
    title: 'Ollama URL и путь к данным моделей',
    keys: [
      { key: 'ollama_gpu_url', label: 'Ollama GPU URL', type: 'text', placeholder: 'http://ollama-gpu:11434' },
      { key: 'ollama_cpu_url', label: 'Ollama CPU URL', type: 'text', placeholder: 'http://ollama-cpu:11434' },
      { key: 'ollama_models_path', label: 'Путь к данным моделей Ollama (на хосте)', type: 'text', placeholder: '/home/ollama-models' },
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
    title: 'Облачные провайдеры (таймауты и URL)',
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
    title: 'Веб-поиск в чате',
    keys: [
      { key: 'web_search_api_key', label: 'Serper API Key (serper.dev)', type: 'text', placeholder: 'опционально — для веб-поиска в чате' },
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

const MAIN_TABS = [
  { id: 'models' as const, label: 'Модели', icon: Cpu },
  { id: 'databases' as const, label: 'Базы данных', icon: Database },
  { id: 'openclaw' as const, label: 'OpenClaw', icon: Bot },
  { id: 'chat' as const, label: 'Чат и сервисы', icon: MessageSquare },
  { id: 'other' as const, label: 'Прочее', icon: Settings2 },
] as const

const MODEL_SUB_TABS = [
  { id: 'local' as const, label: 'Локальные' },
  { id: 'cloud' as const, label: 'Облачные' },
] as const

function renderSection(
  section: SectionDef,
  form: SettingsMap,
  handleChange: (key: string, value: string | number | boolean) => void,
) {
  return (
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
  )
}

export default function SettingsPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const queryClient = useQueryClient()
  const [form, setForm] = useState<SettingsMap>({})
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const [activeTab, setActiveTab] = useState<(typeof MAIN_TABS)[number]['id']>('models')
  const [modelSubTab, setModelSubTab] = useState<(typeof MODEL_SUB_TABS)[number]['id']>('local')
  const [openclawToken, setOpenclawToken] = useState<{ token: string; canvas_path: string } | null>(null)
  const [openclawTokenError, setOpenclawTokenError] = useState<string | null>(null)
  const [openclawTokenLoading, setOpenclawTokenLoading] = useState(false)

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
      <div className="flex-1 overflow-y-auto p-6 flex items-center gap-2 text-slate-400">
        <Loader2 size={20} className="animate-spin" />
        <span>Загрузка настроек...</span>
      </div>
    )
  }

  const sectionQdrant = SECTIONS[3]
  const sectionOpenClaw = SECTIONS[6]
  const sectionsChat = [SECTIONS[2], SECTIONS[4], SECTIONS[7]]
  const sectionOther = SECTIONS[8]
  const sectionCloudOpts = SECTIONS[5]

  const renderTabContent = () => {
    if (activeTab === 'models') {
      return (
        <div className="space-y-6">
          {/* Подвкладки: Локальные | Облачные */}
          <div className="flex gap-1 p-1 rounded-lg bg-surface-800/80 border border-surface-700 w-fit">
            {MODEL_SUB_TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setModelSubTab(id)}
                className={clsx(
                  'px-4 py-2 rounded-md text-sm font-medium transition-colors',
                  modelSubTab === id
                    ? 'bg-surface-700 text-slate-100 shadow'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-surface-700/50',
                )}
              >
                {label}
              </button>
            ))}
          </div>

          {modelSubTab === 'local' && (
            <>
              {renderSection(SECTIONS[0], form, handleChange)}
              {renderSection(SECTIONS[1], form, handleChange)}
              <section className="card p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-2 border-b border-surface-700 pb-2">
                  Загрузка моделей Ollama
                </h3>
                <p className="text-xs text-slate-500 mb-4">
                  Список загруженных моделей по инстансам. Загрузите модель по имени, затем выберите её в «Назначение по ролям».
                </p>
                <LocalModelsTab />
              </section>
              <section className="card p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-2 border-b border-surface-700 pb-2">
                  Назначение по ролям
                </h3>
                <p className="text-xs text-slate-500 mb-4">
                  Выберите модель для чата, анализа чертежей, поиска и переранжирования. Имеет приоритет над полями «по умолчанию» выше.
                </p>
                <AssignmentsBlock />
              </section>
            </>
          )}

          {modelSubTab === 'cloud' && (
            <>
              {renderSection(sectionCloudOpts, form, handleChange)}
              <section className="card p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-2 border-b border-surface-700 pb-2">
                  Облачные провайдеры (API-ключи)
                </h3>
                <CloudModelsTab />
              </section>
            </>
          )}
        </div>
      )
    }

    if (activeTab === 'databases') {
      return <div className="space-y-6">{renderSection(sectionQdrant, form, handleChange)}</div>
    }

    if (activeTab === 'openclaw') {
      const canvasUrl = typeof window !== 'undefined' ? `${window.location.origin}${openclawToken?.canvas_path ?? '/openclaw/__openclaw__/canvas/'}` : ''
      return (
        <div className="space-y-6">
          <section className="card p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-2 border-b border-surface-700 pb-2 flex items-center gap-2">
              <Key size={16} />
              Вход в веб-интерфейс OpenClaw (Control UI)
            </h3>
            <p className="text-xs text-slate-500 mb-4">
              При открытии страницы OpenClaw отображается «Unauthorized» — нужен токен gateway. Нажмите «Показать токен», скопируйте его, откройте ссылку ниже, в настройках Control UI вставьте токен в поле Auth и подключитесь.
            </p>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <button
                type="button"
                onClick={async () => {
                  setOpenclawTokenError(null)
                  setOpenclawTokenLoading(true)
                  try {
                    const res = await api.get<{ token: string; canvas_path: string }>('/admin/openclaw-setup-token')
                    setOpenclawToken(res)
                  } catch (e: unknown) {
                    setOpenclawToken(null)
                    setOpenclawTokenError(e instanceof Error ? e.message : 'Не удалось загрузить токен')
                  } finally {
                    setOpenclawTokenLoading(false)
                  }
                }}
                disabled={openclawTokenLoading}
                className="px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2"
              >
                {openclawTokenLoading ? <Loader2 size={14} className="animate-spin" /> : <Key size={14} />}
                Показать токен
              </button>
              <a
                href={canvasUrl || '/openclaw/__openclaw__/canvas/'}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-2 rounded-lg bg-surface-700 hover:bg-surface-600 text-slate-200 text-sm font-medium flex items-center gap-2"
              >
                <ExternalLink size={14} />
                Открыть OpenClaw
              </a>
            </div>
            {openclawTokenError && (
              <p className="text-sm text-red-400 mb-2">{openclawTokenError}</p>
            )}
            {openclawToken && (
              <div className="space-y-2">
                <label className="block text-xs text-slate-500">Токен (вставьте в Control UI → настройки → Auth)</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    value={openclawToken.token}
                    className="flex-1 px-3 py-2 rounded-lg bg-surface-800 border border-surface-600 text-slate-200 font-mono text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(openclawToken.token)}
                    className="px-3 py-2 rounded-lg bg-surface-700 hover:bg-surface-600 text-slate-300 flex items-center gap-1"
                    title="Копировать"
                  >
                    <Copy size={14} />
                    Копировать
                  </button>
                </div>
              </div>
            )}
          </section>
          {renderSection(sectionOpenClaw, form, handleChange)}
        </div>
      )
    }

    if (activeTab === 'chat') {
      return (
        <div className="space-y-6">
          {sectionsChat.map((s) => renderSection(s, form, handleChange))}
        </div>
      )
    }

    if (activeTab === 'other') {
      return <div className="space-y-6">{renderSection(sectionOther, form, handleChange)}</div>
    }

    return null
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="shrink-0 px-4 pt-4 pb-0 border-b border-surface-700 bg-surface-950/80">
        <h1 className="text-xl font-semibold text-slate-100 mb-2">Настройки системы</h1>
        <p className="text-sm text-slate-500 mb-4">
          Значения имеют приоритет над .env. Пароли БД и JWT задаются только в .env.
        </p>

        {/* Верхний уровень вкладок */}
        <nav className="flex gap-0.5 -mb-px overflow-x-auto" aria-label="Настройки">
          {MAIN_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              className={clsx(
                'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 whitespace-nowrap transition-colors',
                activeTab === id
                  ? 'border-brand-500 text-brand-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-surface-600',
              )}
            >
              <Icon size={18} className="shrink-0" />
              {label}
            </button>
          ))}
        </nav>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <form onSubmit={handleSubmit} className="p-6 max-w-4xl mx-auto pb-10">
          {message && (
            <div
              className={clsx(
                'mb-6 p-3 rounded-lg text-sm flex items-center gap-2',
                message.type === 'ok'
                  ? 'bg-green-500/10 border border-green-500/30 text-green-300'
                  : 'bg-red-500/10 border border-red-500/30 text-red-300',
              )}
            >
              {message.type === 'err' && <AlertCircle size={18} />}
              {message.text}
            </div>
          )}

          {renderTabContent()}

          <div className="flex justify-end pt-8 mt-6 border-t border-surface-700">
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
    </div>
  )
}
