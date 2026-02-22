import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Cpu,
  Cloud,
  RefreshCw,
  Download,
  Loader2,
  AlertTriangle,
  CheckCircle,
  Server,
  Shield,
} from 'lucide-react'
import { api, getToken } from '../api/client'
import type { ProviderInfo, AssignmentsResponse, OllamaInstanceModels } from '../types'
import { useAuthStore } from '../store/auth'
import clsx from 'clsx'

type TabId = 'local' | 'cloud'

// ─── Локальные модели: список + Pull ───────────────────────────────────
function LocalModelsTab() {
  const [pullModel, setPullModel] = useState('')
  const [pullLogs, setPullLogs] = useState<string[]>([])
  const [pullRunning, setPullRunning] = useState(false)
  const queryClient = useQueryClient()

  const { data: ollamaData, isLoading } = useQuery<Record<string, OllamaInstanceModels>>({
    queryKey: ['models', 'local', 'ollama'],
    queryFn: () => api.get<Record<string, OllamaInstanceModels>>('/models/local/ollama'),
  })

  const handlePull = async () => {
    if (!pullModel.trim() || pullRunning) return
    setPullLogs([])
    setPullRunning(true)
    const token = getToken()
    try {
      const res = await fetch('/api/v1/admin/ollama/pull', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ model: pullModel.trim() }),
      })
      if (!res.body) return
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n')
        buf = parts.pop() ?? ''
        for (const p of parts) {
          if (p.startsWith('data: ')) {
            try {
              const ev = JSON.parse(p.slice(6))
              if (ev.type === 'progress' && ev.data?.status) {
                const line =
                  ev.data.completed != null && ev.data.total != null
                    ? `${ev.data.status}: ${Math.round((ev.data.completed / ev.data.total) * 100)}%`
                    : ev.data.status
                setPullLogs((prev) => [...prev.slice(-20), line])
              } else if (ev.type === 'done') {
                setPullLogs((prev) => [...prev, 'Загрузка завершена'])
                queryClient.invalidateQueries({ queryKey: ['models'] })
              } else if (ev.type === 'error') {
                setPullLogs((prev) => [...prev, `Ошибка: ${ev.detail}`])
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      setPullLogs((prev) => [...prev, `Ошибка: ${err}`])
    } finally {
      setPullRunning(false)
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400 flex items-center gap-2">
        <Shield size={16} className="text-green-400" />
        Локальные модели не отправляют данные за пределы вашей инфраструктуры.
      </p>

      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={24} className="animate-spin text-slate-500" />
        </div>
      )}

      {ollamaData && (
        <>
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Ollama GPU (LLM, VLM)
            </h3>
            <div className="card p-4">
              <div className="flex flex-wrap gap-2">
                {ollamaData.gpu?.models?.length
                  ? ollamaData.gpu.models.map((name) => (
                      <span
                        key={name}
                        className="px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 text-sm font-mono"
                      >
                        {name}
                      </span>
                    ))
                  : (
                      <span className="text-slate-500 text-sm">Нет загруженных моделей</span>
                    )}
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Ollama CPU (Embedding, Reranker)
            </h3>
            <div className="card p-4">
              <div className="flex flex-wrap gap-2">
                {ollamaData.cpu?.models?.length
                  ? ollamaData.cpu.models.map((name) => (
                      <span
                        key={name}
                        className="px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300 text-sm font-mono"
                      >
                        {name}
                      </span>
                    ))
                  : (
                      <span className="text-slate-500 text-sm">Нет загруженных моделей</span>
                    )}
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Загрузить модель Ollama
            </h3>
            <div className="card p-4 flex flex-col sm:flex-row gap-2">
              <input
                value={pullModel}
                onChange={(e) => setPullModel(e.target.value)}
                placeholder="qwen3:30b, qwen3-embedding, ..."
                className="input-field flex-1 text-sm"
                onKeyDown={(e) => e.key === 'Enter' && handlePull()}
                disabled={pullRunning}
              />
              <button
                onClick={handlePull}
                disabled={!pullModel.trim() || pullRunning}
                className="btn-primary flex items-center gap-2"
              >
                {pullRunning ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )}
                Загрузить
              </button>
            </div>
            {pullLogs.length > 0 && (
              <div className="mt-2 bg-surface-950 rounded-lg p-3 font-mono text-xs text-green-300 max-h-32 overflow-y-auto">
                {pullLogs.map((l, i) => (
                  <div key={i}>{l}</div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

// ─── Облачные модели: API-ключи в админке, баннер безопасности ───────────
function CloudModelsTab() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'

  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)

  const queryClient = useQueryClient()
  const { data: providers } = useQuery<ProviderInfo[]>({
    queryKey: ['models', 'providers'],
    queryFn: () => api.get<ProviderInfo[]>('/models/providers'),
  })

  const patchProviderKey = useMutation({
    mutationFn: async ({ providerId, apiKey }: { providerId: string; apiKey: string | null }) => {
      await api.patch(`/models/providers/${providerId}`, { api_key: apiKey ?? null })
    },
    onSuccess: (_, { providerId }) => {
      setKeyDrafts((prev) => {
        const next = { ...prev }
        delete next[providerId]
        return next
      })
      setSaveError(null)
      setSaveSuccess(providerId)
      queryClient.invalidateQueries({ queryKey: ['models', 'providers'] })
      setTimeout(() => setSaveSuccess(null), 3000)
    },
    onError: (err: Error) => {
      setSaveError(err.message || 'Не удалось сохранить ключ')
    },
  })

  const cloudProviders = useMemo(
    () => (providers || []).filter((p) => !['ollama_gpu', 'ollama_cpu'].includes(p.type)),
    [providers],
  )

  const handleSaveKey = (providerId: string) => {
    setSaveError(null)
    const value = keyDrafts[providerId]?.trim()
    patchProviderKey.mutate({
      providerId,
      apiKey: value === '' ? null : (value ?? null),
    })
  }

  const handleClearKey = (providerId: string) => {
    setSaveError(null)
    patchProviderKey.mutate({ providerId, apiKey: null })
  }

  return (
    <div className="space-y-6">
      <div
        className="flex items-start gap-3 p-4 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200"
        role="alert"
      >
        <AlertTriangle size={20} className="shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">Безопасность облачных моделей</p>
          <p className="text-sm mt-1 text-amber-200/90">
            Использование облачных моделей для обработки документов может привести к передаче
            данных третьим лицам. Для конфиденциальных данных рекомендуется использовать локальные
            модели (Ollama, vLLM).
          </p>
        </div>
      </div>

      {saveError && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-200 text-sm">
          {saveError}
        </div>
      )}

      {cloudProviders.length === 0 ? (
        <p className="text-slate-500 text-sm">
          Облачные провайдеры пока не добавлены. Настройка API-ключей и списка моделей — в
          разработке.
        </p>
      ) : (
        <div className="space-y-4">
          {cloudProviders.map((p) => (
            <div key={p.id} className="card p-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <span className="font-medium text-slate-200">{p.name}</span>
                {p.api_key_set ? (
                  <span className="text-xs text-green-400 flex items-center gap-1">
                    <CheckCircle size={12} /> Ключ задан
                  </span>
                ) : (
                  <span className="text-xs text-slate-500">Ключ не задан</span>
                )}
              </div>
              {p.models.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.models.slice(0, 10).map((m) => (
                    <span
                      key={m}
                      className="px-2 py-0.5 rounded bg-surface-700 text-slate-400 text-xs font-mono"
                    >
                      {m}
                    </span>
                  ))}
                  {p.models.length > 10 && (
                    <span className="text-slate-500 text-xs">+{p.models.length - 10}</span>
                  )}
                </div>
              )}

              {isAdmin && (
                <div className="mt-4 pt-4 border-t border-surface-700 space-y-2">
                  <label className="block text-xs text-slate-400 font-medium">
                    API-ключ (только для администратора)
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder={p.api_key_set ? '•••••••• — введите новый ключ для замены' : 'Введите API-ключ'}
                      value={keyDrafts[p.id] ?? ''}
                      onChange={(e) =>
                        setKeyDrafts((prev) => ({ ...prev, [p.id]: e.target.value }))
                      }
                      className="flex-1 min-w-[200px] px-3 py-2 rounded-lg bg-surface-800 border border-surface-600 text-slate-200 placeholder:text-slate-500 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 text-sm font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => handleSaveKey(p.id)}
                      disabled={patchProviderKey.isPending}
                      className="px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {patchProviderKey.isPending && patchProviderKey.variables?.providerId === p.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : null}
                      Сохранить ключ
                    </button>
                    {p.api_key_set && (
                      <button
                        type="button"
                        onClick={() => handleClearKey(p.id)}
                        disabled={patchProviderKey.isPending}
                        className="px-3 py-2 rounded-lg bg-surface-700 hover:bg-surface-600 text-slate-300 text-sm disabled:opacity-50"
                      >
                        Удалить ключ
                      </button>
                    )}
                  </div>
                  {saveSuccess === p.id && (
                    <p className="text-xs text-green-400">Ключ сохранён.</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Назначение по ролям ───────────────────────────────────────────────
function AssignmentsBlock() {
  const queryClient = useQueryClient()
  const [savingRole, setSavingRole] = useState<string | null>(null)
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const { data: assignments } = useQuery<AssignmentsResponse>({
    queryKey: ['models', 'assignments'],
    queryFn: () => api.get<AssignmentsResponse>('/models/assignments'),
  })

  const { data: providers } = useQuery<ProviderInfo[]>({
    queryKey: ['models', 'providers'],
    queryFn: () => api.get<ProviderInfo[]>('/models/providers'),
  })

  const putAssignment = useMutation({
    mutationFn: (body: { role: string; provider_id: string; model_id: string }) =>
      api.put('/models/assignments', body),
    onSuccess: (_, vars) => {
      setSavingRole(null)
      setMessage({ type: 'ok', text: 'Настройки применены' })
      queryClient.invalidateQueries({ queryKey: ['models', 'assignments'] })
      setTimeout(() => setMessage(null), 3000)
    },
    onError: (err: Error) => {
      setSavingRole(null)
      setMessage({ type: 'err', text: err.message || 'Ошибка сохранения' })
    },
  })

  const roleKeys: (keyof AssignmentsResponse)[] = ['llm', 'vlm', 'embedding', 'reranker']

  const options = useMemo(() => {
    if (!providers) return []
    const seen = new Set<string>()
    const list: { value: string; label: string; providerId: string; modelId: string }[] = []
    for (const p of providers) {
      for (const m of p.models) {
        const value = `${p.id}:${m}`
        if (seen.has(value)) continue
        seen.add(value)
        list.push({
          value,
          label: `${p.name}: ${m}`,
          providerId: p.id,
          modelId: m,
        })
      }
    }
    if (assignments) {
      for (const key of roleKeys) {
        const a = assignments[key]
        if (!a?.provider_id || !a?.model_id) continue
        const value = `${a.provider_id}:${a.model_id}`
        if (seen.has(value)) continue
        seen.add(value)
        const providerName = providers.find((x) => x.id === a.provider_id)?.name ?? a.provider_type
        list.push({
          value,
          label: `${providerName}: ${a.model_id} (текущее)`,
          providerId: a.provider_id,
          modelId: a.model_id,
        })
      }
    }
    return list.sort((x, y) => x.label.localeCompare(y.label))
  }, [providers, assignments])

  const roles: { key: keyof AssignmentsResponse; label: string; warnCloud?: boolean }[] = [
    { key: 'llm', label: 'LLM (чат, генерация)' },
    { key: 'vlm', label: 'VLM (анализ чертежей)' },
    { key: 'embedding', label: 'Embedding (поиск по документам)', warnCloud: true },
    { key: 'reranker', label: 'Reranker (переранжирование)', warnCloud: true },
  ]

  if (!assignments || !providers) return null

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
        <Server size={16} />
        Назначение по ролям
      </h2>
      {message && (
        <div
          className={clsx(
            'text-sm px-3 py-2 rounded-lg flex items-center gap-2',
            message.type === 'ok' ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400',
          )}
        >
          {message.type === 'ok' ? <CheckCircle size={16} /> : <AlertTriangle size={16} />}
          {message.text}
        </div>
      )}
      <div className="card divide-y divide-surface-700">
        {roles.map(({ key, label, warnCloud }) => {
          const a = assignments[key]
          const currentValue = a ? `${a.provider_id}:${a.model_id}` : ''
          const isCloud = a?.is_cloud
          return (
            <div key={key} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="flex items-center gap-2 min-w-[180px]">
                <span className="text-sm text-slate-400">{label}</span>
                {warnCloud && isCloud && (
                  <span
                    className="text-amber-400"
                    title="Облачная модель: данные могут передаваться третьим лицам"
                  >
                    <AlertTriangle size={14} />
                  </span>
                )}
              </div>
              <select
                value={currentValue}
                onChange={(e) => {
                  const v = e.target.value
                  const opt = options.find((o) => o.value === v)
                  if (!opt) return
                  setSavingRole(key)
                  putAssignment.mutate({
                    role: key,
                    provider_id: opt.providerId,
                    model_id: opt.modelId,
                  })
                }}
                disabled={savingRole !== null}
                className="bg-surface-700 border border-surface-600 text-slate-200 rounded-lg px-3 py-2 text-sm min-w-[240px] focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {options.length === 0 ? (
                  <option value="">Нет вариантов</option>
                ) : (
                  options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))
                )}
              </select>
              {savingRole === key && (
                <Loader2 size={14} className="animate-spin text-slate-400" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Страница ──────────────────────────────────────────────────────────
export default function ModelsPage() {
  const [tab, setTab] = useState<TabId>('local')

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Настройка моделей</h1>
          <p className="text-sm text-slate-500 mt-1">
            Локальные (Ollama, vLLM) и облачные провайдеры. Назначьте модели для каждой роли.
          </p>
        </div>

        {/* Табы */}
        <div className="flex gap-2 border-b border-surface-700 pb-2">
          <button
            onClick={() => setTab('local')}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              tab === 'local'
                ? 'bg-accent/15 text-accent-light'
                : 'text-slate-400 hover:bg-surface-800 hover:text-slate-200',
            )}
          >
            <Cpu size={16} />
            Локальные
          </button>
          <button
            onClick={() => setTab('cloud')}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              tab === 'cloud'
                ? 'bg-accent/15 text-accent-light'
                : 'text-slate-400 hover:bg-surface-800 hover:text-slate-200',
            )}
          >
            <Cloud size={16} />
            Облачные
          </button>
        </div>

        {tab === 'local' && <LocalModelsTab />}
        {tab === 'cloud' && <CloudModelsTab />}

        <AssignmentsBlock />
      </div>
    </div>
  )
}
