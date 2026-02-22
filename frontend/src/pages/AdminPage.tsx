import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server, RefreshCw, Play, Square, RotateCcw, FileText,
  Cpu, HardDrive, MemoryStick, Clock, Zap,
  ChevronRight, AlertCircle, CheckCircle, XCircle,
  PackageOpen, Database, X, Loader2, Activity,
  Terminal, ChevronDown
} from 'lucide-react'
import { api } from '../api/client'
import clsx from 'clsx'

// ── Типы ─────────────────────────────────────────────────────────────

interface ContainerInfo {
  id: string
  name: string
  status: string
  health: string | null
  image: string
  created: string
  started_at: string | null
  cpu_percent: number | null
  memory_mb: number | null
  memory_limit_mb: number | null
  memory_percent: number | null
  ports: string[]
}

interface SystemInfo {
  cpu_count: number
  cpu_percent: number
  memory_total_gb: number
  memory_used_gb: number
  memory_percent: number
  disk_total_gb: number
  disk_used_gb: number
  disk_percent: number
  uptime_hours: number
}

// ── Цветовая схема статусов ───────────────────────────────────────────
const STATUS_COLORS: Record<string, { dot: string; badge: string; label: string }> = {
  running:    { dot: 'bg-green-400',  badge: 'bg-green-500/15 text-green-400',  label: 'Работает' },
  healthy:    { dot: 'bg-green-400',  badge: 'bg-green-500/15 text-green-400',  label: 'Здоров' },
  unhealthy:  { dot: 'bg-red-400',    badge: 'bg-red-500/15 text-red-400',      label: 'Проблема' },
  starting:   { dot: 'bg-yellow-400', badge: 'bg-yellow-500/15 text-yellow-400', label: 'Запуск' },
  exited:     { dot: 'bg-slate-500',  badge: 'bg-slate-500/15 text-slate-400',  label: 'Остановлен' },
  paused:     { dot: 'bg-blue-400',   badge: 'bg-blue-500/15 text-blue-400',    label: 'Пауза' },
  restarting: { dot: 'bg-amber-400',  badge: 'bg-amber-500/15 text-amber-400',  label: 'Перезапуск' },
}

const getStatus = (c: ContainerInfo) => {
  const key = c.health ?? c.status
  return STATUS_COLORS[key] ?? STATUS_COLORS['exited']
}

// ── Компонент: карточка контейнера ────────────────────────────────────
function ContainerCard({
  container,
  isSelected,
  onSelect,
  onAction,
  loading,
}: {
  container: ContainerInfo
  isSelected: boolean
  onSelect: () => void
  onAction: (action: 'restart' | 'stop' | 'start') => void
  loading: string | null
}) {
  const st = getStatus(container)
  const isRunning = container.status === 'running'

  return (
    <div
      onClick={onSelect}
      className={clsx(
        'card p-4 cursor-pointer transition-all duration-150 select-none',
        isSelected ? 'border-accent/50 shadow-accent/10 shadow-md' : 'hover:border-surface-600',
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        {/* Имя + статус */}
        <div className="flex items-center gap-2 min-w-0">
          <span className={clsx('w-2 h-2 rounded-full shrink-0', st.dot, isRunning && 'animate-pulse')} />
          <span className="font-semibold text-sm text-slate-200 truncate">{container.name}</span>
        </div>
        <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium shrink-0', st.badge)}>
          {st.label}
        </span>
      </div>

      {/* Метрики */}
      {isRunning && (
        <div className="grid grid-cols-2 gap-2 mb-3 text-xs text-slate-500">
          <div className="flex items-center gap-1">
            <Cpu size={11} />
            <span>{container.cpu_percent != null ? `${container.cpu_percent}%` : '—'}</span>
          </div>
          <div className="flex items-center gap-1">
            <MemoryStick size={11} />
            <span>
              {container.memory_mb != null
                ? `${container.memory_mb < 1024
                    ? container.memory_mb + ' МБ'
                    : (container.memory_mb / 1024).toFixed(1) + ' ГБ'}`
                : '—'}
            </span>
          </div>
        </div>
      )}

      {/* Memory bar */}
      {isRunning && container.memory_percent != null && (
        <div className="mb-3">
          <div className="h-1 bg-surface-700 rounded-full overflow-hidden">
            <div
              className={clsx(
                'h-full rounded-full transition-all',
                container.memory_percent > 85 ? 'bg-red-500' :
                container.memory_percent > 60 ? 'bg-amber-500' : 'bg-accent/70',
              )}
              style={{ width: `${Math.min(container.memory_percent, 100)}%` }}
            />
          </div>
          <p className="text-xs text-slate-600 mt-0.5">RAM {container.memory_percent}%</p>
        </div>
      )}

      {/* Порты */}
      {container.ports.length > 0 && (
        <p className="text-xs text-slate-600 font-mono mb-3 truncate">
          {container.ports.slice(0, 3).join(', ')}
        </p>
      )}

      {/* Кнопки */}
      <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => onAction('restart')}
          disabled={loading !== null}
          className={clsx(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
            'bg-surface-700 text-slate-300 hover:bg-surface-600 disabled:opacity-50',
          )}
          title="Перезапустить"
        >
          {loading === 'restart' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
          Рестарт
        </button>

        {isRunning ? (
          <button
            onClick={() => onAction('stop')}
            disabled={loading !== null}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium
                       bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
            title="Остановить"
          >
            {loading === 'stop' ? <Loader2 size={12} className="animate-spin" /> : <Square size={12} />}
            Стоп
          </button>
        ) : (
          <button
            onClick={() => onAction('start')}
            disabled={loading !== null}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium
                       bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors disabled:opacity-50"
            title="Запустить"
          >
            {loading === 'start' ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Старт
          </button>
        )}

        <button
          onClick={onSelect}
          className={clsx(
            'ml-auto flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors',
            isSelected
              ? 'bg-accent/15 text-accent-light'
              : 'text-slate-500 hover:bg-surface-700 hover:text-slate-300',
          )}
          title="Логи"
        >
          <Terminal size={12} />
          Логи
        </button>
      </div>
    </div>
  )
}

// ── Компонент: просмотр логов ─────────────────────────────────────────
function LogViewer({ containerName, onClose }: { containerName: string; onClose: () => void }) {
  const [lines, setLines] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tail, setTail] = useState(200)
  const [paused, setPaused] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  pausedRef.current = paused

  const connect = useCallback(async (tailCount: number) => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setLines([])
    setConnected(false)
    setError(null)

    const token = getToken()
    try {
      const res = await fetch(
        `/api/v1/admin/containers/${containerName}/logs?tail=${tailCount}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('No body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      setConnected(true)

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          if (part.startsWith('data: ')) {
            try {
              const ev = JSON.parse(part.slice(6))
              if (ev.type === 'log' && !pausedRef.current) {
                setLines((prev) => {
                  const next = [...prev, ev.line]
                  return next.length > 2000 ? next.slice(-2000) : next
                })
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(String(err))
      }
    } finally {
      setConnected(false)
    }
  }, [containerName])

  useEffect(() => {
    connect(tail)
    return () => { abortRef.current?.abort() }
  }, [connect, tail])

  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines, paused])

  const handleClear = () => setLines([])

  return (
    <div className="flex flex-col h-full">
      {/* Заголовок */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3 border-b border-surface-700">
        <Terminal size={16} className="text-slate-400" />
        <span className="font-mono text-sm text-slate-200">{containerName}</span>
        <span className={clsx(
          'text-xs px-2 py-0.5 rounded-full',
          connected ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/15 text-slate-400',
        )}>
          {connected ? '● live' : '○ отключено'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {/* Tail selector */}
          <select
            value={tail}
            onChange={(e) => setTail(Number(e.target.value))}
            className="bg-surface-700 border border-surface-600 text-xs text-slate-300 rounded px-2 py-1 focus:outline-none"
          >
            <option value={50}>Последние 50</option>
            <option value={200}>Последние 200</option>
            <option value={500}>Последние 500</option>
          </select>
          <button onClick={() => setPaused(!paused)} className={clsx(
            'text-xs px-2 py-1 rounded transition-colors',
            paused ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25' : 'btn-ghost',
          )}>
            {paused ? 'Возобновить' : 'Пауза'}
          </button>
          <button onClick={handleClear} className="btn-ghost text-xs">Очистить</button>
          <button onClick={() => connect(tail)} className="btn-ghost text-xs">
            <RefreshCw size={13} />
          </button>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Лог */}
      <div className="flex-1 overflow-y-auto bg-surface-950 p-4 font-mono text-xs leading-5 text-green-300">
        {error && (
          <div className="flex items-center gap-2 text-red-400 mb-2">
            <AlertCircle size={14} />
            {error}
          </div>
        )}
        {lines.length === 0 && !error && (
          <span className="text-slate-600">Ожидание логов...</span>
        )}
        {lines.map((line, i) => (
          <div key={i} className="hover:bg-surface-800/50 px-1 whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

// ── Компонент: системные метрики ──────────────────────────────────────
function SystemMetricsBar({ data }: { data: SystemInfo }) {
  const MetricItem = ({
    icon: Icon,
    label,
    value,
    sub,
    pct,
    warn,
  }: {
    icon: typeof Cpu
    label: string
    value: string
    sub: string
    pct?: number
    warn?: boolean
  }) => (
    <div className="flex items-center gap-3 px-4 py-3 border-r border-surface-700 last:border-0">
      <div className={clsx(
        'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
        warn ? 'bg-amber-500/15' : 'bg-surface-700',
      )}>
        <Icon size={16} className={warn ? 'text-amber-400' : 'text-slate-400'} />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500">{label}</p>
        <p className="text-sm font-semibold text-slate-200">{value}</p>
        {pct !== undefined && (
          <div className="mt-1 h-0.5 w-24 bg-surface-600 rounded-full">
            <div
              className={clsx('h-full rounded-full', pct > 85 ? 'bg-red-400' : pct > 60 ? 'bg-amber-400' : 'bg-accent/70')}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
        )}
        <p className="text-xs text-slate-600">{sub}</p>
      </div>
    </div>
  )

  const uptimeStr = data.uptime_hours < 24
    ? `${Math.floor(data.uptime_hours)}ч ${Math.floor((data.uptime_hours % 1) * 60)}м`
    : `${Math.floor(data.uptime_hours / 24)}д ${Math.floor(data.uptime_hours % 24)}ч`

  return (
    <div className="card flex flex-wrap overflow-hidden">
      <MetricItem
        icon={Cpu}
        label="CPU"
        value={`${data.cpu_percent}%`}
        sub={`${data.cpu_count} ядер`}
        pct={data.cpu_percent}
        warn={data.cpu_percent > 85}
      />
      <MetricItem
        icon={MemoryStick}
        label="RAM"
        value={`${data.memory_used_gb} ГБ`}
        sub={`из ${data.memory_total_gb} ГБ (${data.memory_percent}%)`}
        pct={data.memory_percent}
        warn={data.memory_percent > 85}
      />
      <MetricItem
        icon={HardDrive}
        label="Диск"
        value={`${data.disk_used_gb} ГБ`}
        sub={`из ${data.disk_total_gb} ГБ (${data.disk_percent}%)`}
        pct={data.disk_percent}
        warn={data.disk_percent > 85}
      />
      <MetricItem
        icon={Clock}
        label="Uptime"
        value={uptimeStr}
        sub="время работы"
      />
    </div>
  )
}

// ── Главная страница ──────────────────────────────────────────────────
export default function AdminPage() {
  const qc = useQueryClient()
  const [selectedContainer, setSelectedContainer] = useState<string | null>(null)
  const [containerLoading, setContainerLoading] = useState<Record<string, string | null>>({})

  const { data: containers = [], isFetching: containersFetching } = useQuery<ContainerInfo[]>({
    queryKey: ['containers'],
    queryFn: () => api.get<ContainerInfo[]>('/admin/containers'),
    refetchInterval: 10_000,
  })

  const { data: sysInfo } = useQuery<SystemInfo>({
    queryKey: ['system-info'],
    queryFn: () => api.get<SystemInfo>('/admin/system'),
    refetchInterval: 5_000,
  })

  const handleAction = async (name: string, action: 'restart' | 'stop' | 'start') => {
    setContainerLoading((prev) => ({ ...prev, [name]: action }))
    try {
      await api.post(`/admin/containers/${name}/${action}`)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['containers'] }), 1500)
    } catch (err) {
      console.error(err)
    } finally {
      setContainerLoading((prev) => ({ ...prev, [name]: null }))
    }
  }

  // Разделяем контейнеры по группам
  const coreContainers = containers.filter((c) =>
    ['api', 'frontend', 'caddy', 'nginx'].includes(c.name)
  )
  const aiContainers = containers.filter((c) =>
    c.name.startsWith('ollama')
  )
  const dbContainers = containers.filter((c) =>
    ['postgres', 'neo4j', 'qdrant'].includes(c.name)
  )
  const otherContainers = containers.filter((c) =>
    !coreContainers.includes(c) && !aiContainers.includes(c) && !dbContainers.includes(c)
  )

  const ContainerGroup = ({ title, items }: { title: string; items: ContainerInfo[] }) => {
    if (items.length === 0) return null
    return (
      <div>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">{title}</h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {items.map((c) => (
            <ContainerCard
              key={c.name}
              container={c}
              isSelected={selectedContainer === c.name}
              onSelect={() => setSelectedContainer(selectedContainer === c.name ? null : c.name)}
              onAction={(action) => handleAction(c.name, action)}
              loading={containerLoading[c.name] ?? null}
            />
          ))}
        </div>
      </div>
    )
  }

  const runningCount = containers.filter((c) => c.status === 'running').length

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Основная область ── */}
      <div className={clsx(
        'flex flex-col flex-1 min-w-0 overflow-y-auto transition-all duration-300',
        selectedContainer ? 'w-1/2' : 'w-full',
      )}>
        <div className="p-6 space-y-6">
          {/* Заголовок */}
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-slate-100">Управление системой</h1>
              <p className="text-sm text-slate-500 mt-1">
                {runningCount} из {containers.length} сервисов работают
              </p>
            </div>
            <button
              onClick={() => qc.invalidateQueries({ queryKey: ['containers', 'system-info'] })}
              className="btn-ghost"
            >
              <RefreshCw size={15} className={containersFetching ? 'animate-spin' : ''} />
              Обновить
            </button>
          </div>

          {/* Системные метрики */}
          {sysInfo && <SystemMetricsBar data={sysInfo} />}

          {/* Контейнеры */}
          <ContainerGroup title="Веб-сервисы" items={coreContainers} />
          <ContainerGroup title="AI / Ollama" items={aiContainers} />
          <ContainerGroup title="Базы данных" items={dbContainers} />
          <ContainerGroup title="Прочие" items={otherContainers} />

          {/* Быстрые действия */}
          <div className="card p-5 space-y-5">
            <h2 className="text-sm font-semibold text-slate-200">Быстрые действия</h2>

            {/* Загрузка и выбор моделей — в Настройках */}
            <div className="text-sm text-slate-400">
              Загрузка и выбор моделей Ollama:{' '}
              <Link to="/settings" className="text-accent-light hover:underline font-medium">Настройки</Link>
              {' '}→ блоки «Загрузка моделей Ollama» и «Назначение по ролям».
            </div>

            {/* ETL */}
            <div>
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Индексация документов
              </h3>
              <div className="flex flex-wrap gap-2">
                {['excel', 'pdf', 'blueprints', 'techprocess', 'all'].map((task) => (
                  <button
                    key={task}
                    onClick={() => {
                      // Открываем лог ingestion контейнера при запуске
                      setSelectedContainer('ingestion')
                      api.post(`/admin/ingest/${task}`).catch(console.error)
                    }}
                    className="btn-ghost text-xs"
                  >
                    <Database size={12} />
                    {task === 'all' ? 'Всё сразу' : `ingest-${task}`}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Панель логов ── */}
      {selectedContainer && (
        <div className="w-1/2 border-l border-surface-700 flex flex-col animate-slide-up">
          <LogViewer
            containerName={selectedContainer}
            onClose={() => setSelectedContainer(null)}
          />
        </div>
      )}
    </div>
  )
}
