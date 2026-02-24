import { useQuery } from '@tanstack/react-query'
import {
  Activity, CheckCircle, XCircle, Clock, Database,
  Cpu, HardDrive, RefreshCw, Zap, Server, Cloud
} from 'lucide-react'
import { api } from '../api/client'
import type { SystemStatus, AssignmentsResponse } from '../types'
import clsx from 'clsx'

function ServiceCard({ service }: { service: SystemStatus['services'][number] }) {
  const isOk = service.status === 'ok'
  return (
    <div className="card p-4 flex items-start gap-3">
      <div
        className={clsx(
          'w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
          isOk ? 'bg-green-500/15' : 'bg-red-500/15',
        )}
      >
        <Server size={18} className={isOk ? 'text-green-400' : 'text-red-400'} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-slate-200">{service.name}</p>
          <span className={isOk ? 'badge-ok' : 'badge-error'}>
            {isOk ? (
              <><CheckCircle size={10} /> OK</>
            ) : (
              <><XCircle size={10} /> Ошибка</>
            )}
          </span>
        </div>
        {service.latency_ms !== null && service.latency_ms !== undefined && (
          <p className="text-xs text-slate-500 mt-0.5">
            <Clock size={10} className="inline mr-1" />
            {service.latency_ms} мс
          </p>
        )}
        {service.detail && (
          <p className="text-xs text-slate-500 mt-1 truncate">{service.detail}</p>
        )}
      </div>
    </div>
  )
}

export default function StatusPage() {
  const {
    data: status,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery<SystemStatus>({
    queryKey: ['system-status'],
    queryFn: () => api.get<SystemStatus>('/system/status'),
    refetchInterval: 30_000,
  })

  const { data: assignments } = useQuery<AssignmentsResponse>({
    queryKey: ['models', 'assignments'],
    queryFn: () => api.get<AssignmentsResponse>('/models/assignments'),
    refetchInterval: 30_000,
  })

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Заголовок */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-100">Статус системы</h1>
            <p className="text-sm text-slate-500 mt-1">Обновляется каждые 30 секунд</p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn-ghost"
          >
            <RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} />
            Обновить
          </button>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <RefreshCw size={24} className="animate-spin text-slate-500" />
          </div>
        )}

        {error && (
          <div className="card p-4 flex items-center gap-3">
            <XCircle size={18} className="text-red-400 shrink-0" />
            <p className="text-sm text-red-300">Не удалось загрузить статус. Проверьте соединение.</p>
          </div>
        )}

        {status && (
          <>
            {/* Сервисы */}
            <section>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Сервисы
              </h2>
              <div className="grid sm:grid-cols-2 gap-3">
                {status.services.map((svc) => (
                  <ServiceCard key={svc.name} service={svc} />
                ))}
              </div>
            </section>

            {/* VRAM */}
            <section>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                VRAM / GPU
              </h2>
              <div className="card p-4 grid sm:grid-cols-3 gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-violet-500/15 flex items-center justify-center">
                    <Zap size={18} className="text-violet-400" />
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Текущая модель</p>
                    <p className="text-sm font-medium text-slate-200 mt-0.5">
                      {status.vram.current_model ?? 'Не загружена'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className={clsx(
                    'w-9 h-9 rounded-lg flex items-center justify-center',
                    status.vram.gpu_available ? 'bg-green-500/15' : 'bg-surface-700',
                  )}>
                    <Cpu size={18} className={status.vram.gpu_available ? 'text-green-400' : 'text-slate-500'} />
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">GPU</p>
                    <p className="text-sm font-medium text-slate-200 mt-0.5">
                      {status.vram.gpu_available ? 'Доступен' : 'Нет данных'}
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* Модели */}
            <section>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Конфигурация моделей
              </h2>
              <div className="card divide-y divide-surface-700">
                {(assignments
                  ? [
                      { label: 'LLM (GPU)', a: assignments.llm },
                      { label: 'VLM (GPU)', a: assignments.vlm },
                      { label: 'Embedding (CPU)', a: assignments.embedding },
                      { label: 'Reranker (CPU)', a: assignments.reranker },
                    ]
                  : [
                      { label: 'LLM (GPU)', a: { model_id: status.llm_model, is_cloud: false } },
                      { label: 'VLM (GPU)', a: { model_id: status.vlm_model, is_cloud: false } },
                      { label: 'Embedding (CPU)', a: { model_id: status.embedding_model, is_cloud: false } },
                      { label: 'Reranker (CPU)', a: { model_id: status.reranker_model, is_cloud: false } },
                    ]
                ).map(({ label, a }) => (
                  <div key={label} className="flex items-center justify-between px-4 py-3 gap-2">
                    <span className="text-sm text-slate-400">{label}</span>
                    <span className="flex items-center gap-2 min-w-0">
                      {a.is_cloud && (
                        <span className="shrink-0 text-amber-400" title="Облачная модель">
                          <Cloud size={14} />
                        </span>
                      )}
                      <code className="text-sm font-mono text-accent-light truncate">{a.model_id}</code>
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* Использование диска */}
            <section>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Хранилище документов
              </h2>
              <div className="card divide-y divide-surface-700">
                {status.disk_usage.map((d) => {
                  const totalFiles = status.disk_usage.reduce((a, b) => a + b.files_count, 0)
                  const pct = totalFiles > 0 ? (d.files_count / Math.max(totalFiles, 1)) * 100 : 0
                  return (
                    <div key={d.folder} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <HardDrive size={13} className="text-slate-500" />
                          <span className="text-sm text-slate-300 font-mono">{d.folder}</span>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-slate-500">
                          <span>{d.files_count} файл{d.files_count === 1 ? '' : d.files_count < 5 ? 'а' : 'ов'}</span>
                          <span>{d.total_size_mb.toFixed(1)} МБ</span>
                        </div>
                      </div>
                      <div className="h-1 bg-surface-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-accent/60 rounded-full transition-all duration-500"
                          style={{ width: `${Math.max(pct, d.files_count > 0 ? 4 : 0)}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            {/* Файлы в обработке / с ошибками */}
            {status.files_with_errors && status.files_with_errors.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  Проблемные файлы
                </h2>
                <div className="card divide-y divide-surface-700">
                  {status.files_with_errors.map((file: any) => (
                    <div key={file.id} className="px-4 py-3">
                      <div className="flex items-start gap-3">
                        {file.status === 'processing' ? (
                          <Loader2 size={18} className="text-amber-400 shrink-0 animate-spin mt-0.5" />
                        ) : (
                          <XCircle size={18} className="text-red-400 shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-200 truncate">{file.filename}</p>
                          <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-500">
                            <span className="font-mono">{file.folder}</span>
                            <span>·</span>
                            <span className={file.status === 'processing' ? 'text-amber-400' : 'text-red-400'}>
                              {file.status === 'processing' ? 'Индексация...' : 'Ошибка'}
                            </span>
                          </div>
                          {file.error_msg && (
                            <p className="text-xs text-red-400 mt-1 truncate">{file.error_msg}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
