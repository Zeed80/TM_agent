import { useState, useRef, DragEvent, ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { Upload, FolderOpen, CheckCircle, AlertCircle, X, FileText, Image, Table, Play } from 'lucide-react'
import { uploadFile, ApiError } from '../api/client'
import { useAuthStore } from '../store/auth'
import clsx from 'clsx'

const FOLDERS = [
  {
    id: 'blueprints',
    label: 'Чертежи',
    description: 'PNG, JPEG, PDF, TIFF — чертежи деталей и узлов',
    icon: Image,
    accept: '.png,.jpg,.jpeg,.webp,.pdf,.tiff,.tif',
    color: 'text-blue-400',
    bg: 'bg-blue-400/10 border-blue-400/20',
  },
  {
    id: 'invoices',
    label: 'Счета',
    description: 'PNG, JPEG, PDF, TIFF — счета, накладные, акты',
    icon: FileText,
    accept: '.png,.jpg,.jpeg,.webp,.pdf,.tiff,.tif',
    color: 'text-teal-400',
    bg: 'bg-teal-400/10 border-teal-400/20',
  },
  {
    id: 'manuals',
    label: 'Инструкции',
    description: 'PDF, DOCX, TXT — руководства по эксплуатации',
    icon: FileText,
    accept: '.pdf,.docx,.doc,.txt',
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/10 border-emerald-400/20',
  },
  {
    id: 'gosts',
    label: 'ГОСТы',
    description: 'PDF, DOCX — стандарты и нормативные документы',
    icon: FileText,
    accept: '.pdf,.docx,.doc',
    color: 'text-violet-400',
    bg: 'bg-violet-400/10 border-violet-400/20',
  },
  {
    id: 'emails',
    label: 'Переписка',
    description: 'EML, MSG, TXT — деловая переписка',
    icon: FileText,
    accept: '.eml,.msg,.txt',
    color: 'text-amber-400',
    bg: 'bg-amber-400/10 border-amber-400/20',
  },
  {
    id: 'catalogs',
    label: 'Каталоги',
    description: 'XLSX, CSV — каталоги инструмента и материалов',
    icon: Table,
    accept: '.xlsx,.xls,.csv',
    color: 'text-cyan-400',
    bg: 'bg-cyan-400/10 border-cyan-400/20',
  },
  {
    id: 'tech_processes',
    label: 'Техпроцессы',
    description: 'XLSX, CSV — маршрутные карты и операции',
    icon: Table,
    accept: '.xlsx,.xls,.csv',
    color: 'text-rose-400',
    bg: 'bg-rose-400/10 border-rose-400/20',
  },
] as const

type FolderId = (typeof FOLDERS)[number]['id']

interface UploadItem {
  id: string
  file: File
  folder: FolderId
  status: 'pending' | 'uploading' | 'done' | 'error'
  progress: number
  message: string
  error: string
}

/** Кнопка «Запустить индексацию»: только для admin, запускает ingest-all без ожидания конца. */
function StartIndexingButton() {
  const { user } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const handleStart = async () => {
    if (user?.role !== 'admin' || loading) return
    setLoading(true)
    setMessage(null)
    const token = localStorage.getItem('access_token')
    try {
      const res = await fetch('/api/v1/admin/ingest/all', {
        method: 'POST',
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || res.statusText)
      }
      setMessage('Индексация запущена')
      setLoading(false)
      if (res.body) {
        const reader = res.body.getReader()
        void (async () => {
          try {
            while (true) {
              const { done } = await reader.read()
              if (done) break
            }
          } catch {
            // игнорируем ошибки фона
          }
        })()
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  if (user?.role !== 'admin') {
    return (
      <Link to="/admin" className="btn-primary text-sm inline-flex items-center gap-2">
        <Play size={14} />
        Индексация в Управлении
      </Link>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleStart}
        disabled={loading}
        className="btn-primary text-sm inline-flex items-center gap-2 disabled:opacity-50"
      >
        {loading ? (
          <span className="animate-pulse">Запуск…</span>
        ) : (
          <>
            <Play size={14} />
            Запустить индексацию
          </>
        )}
      </button>
      {message && (
        <span className={message === 'Запущено' ? 'text-green-400 text-xs' : 'text-red-400 text-xs'}>
          {message}
        </span>
      )}
    </div>
  )
}

export default function UploadPage() {
  const [selectedFolder, setSelectedFolder] = useState<FolderId>('blueprints')
  const [isDragging, setIsDragging] = useState(false)
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const selectedFolderInfo = FOLDERS.find((f) => f.id === selectedFolder)!

  const processFiles = async (files: File[]) => {
    const newItems: UploadItem[] = files.map((f) => ({
      id: `${Date.now()}-${Math.random()}`,
      file: f,
      folder: selectedFolder,
      status: 'pending',
      progress: 0,
      message: '',
      error: '',
    }))

    setUploads((prev) => [...newItems, ...prev])

    for (const item of newItems) {
      setUploads((prev) =>
        prev.map((u) => (u.id === item.id ? { ...u, status: 'uploading' } : u)),
      )

      try {
        const result = await uploadFile(
          item.folder,
          item.file,
          (pct) =>
            setUploads((prev) =>
              prev.map((u) => (u.id === item.id ? { ...u, progress: pct } : u)),
            ),
        )
        setUploads((prev) =>
          prev.map((u) =>
            u.id === item.id
              ? { ...u, status: 'done', progress: 100, message: result.message }
              : u,
          ),
        )
      } catch (err) {
        const detail =
          err instanceof ApiError ? (err.detail ?? err.message) : String(err)
        setUploads((prev) =>
          prev.map((u) =>
            u.id === item.id ? { ...u, status: 'error', error: detail } : u,
          ),
        )
      }
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) processFiles(files)
  }

  const handleFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length) processFiles(files)
    e.target.value = ''
  }

  const removeUpload = (id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id))
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} Б`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Заголовок */}
        <div>
          <h1 className="text-xl font-bold text-slate-100">Загрузка документов</h1>
          <p className="text-sm text-slate-500 mt-1">
            Загружайте документы для индексации и поиска. После загрузки запустите индексацию кнопкой ниже или в разделе Управление.
          </p>
        </div>

        {/* Выбор папки */}
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Тип документа
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {FOLDERS.map((folder) => {
              const Icon = folder.icon
              const isSelected = selectedFolder === folder.id
              return (
                <button
                  key={folder.id}
                  onClick={() => setSelectedFolder(folder.id)}
                  className={clsx(
                    'flex items-start gap-3 p-3 rounded-xl border text-left transition-all duration-150',
                    isSelected
                      ? `${folder.bg} border-current ${folder.color}`
                      : 'bg-surface-800 border-surface-700 text-slate-400 hover:border-surface-600 hover:text-slate-300',
                  )}
                >
                  <Icon size={16} className={clsx('shrink-0 mt-0.5', isSelected ? folder.color : '')} />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold truncate">{folder.label}</p>
                    <p className="text-xs opacity-70 mt-0.5 leading-tight hidden sm:block">{folder.description}</p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* Зона перетаскивания */}
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            'border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center',
            'cursor-pointer transition-all duration-200 text-center',
            isDragging
              ? 'border-accent bg-accent/5 scale-[1.01]'
              : 'border-surface-600 hover:border-surface-500 hover:bg-surface-800/50',
          )}
        >
          <div className={clsx(
            'w-14 h-14 rounded-2xl flex items-center justify-center mb-4 transition-colors',
            isDragging ? 'bg-accent/20' : 'bg-surface-700',
          )}>
            <Upload size={24} className={isDragging ? 'text-accent-light' : 'text-slate-400'} />
          </div>
          <p className="text-sm font-medium text-slate-200">
            {isDragging ? 'Отпустите файлы...' : 'Перетащите файлы или нажмите для выбора'}
          </p>
          <p className="text-xs text-slate-500 mt-2">
            Папка: <span className={selectedFolderInfo.color}>{selectedFolderInfo.label}</span>
            {' '}&middot; {selectedFolderInfo.accept.replace(/\./g, '').toUpperCase()} &middot; до 50 МБ
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={selectedFolderInfo.accept}
            className="hidden"
            onChange={handleFileInput}
          />
        </div>

        {/* Список загрузок */}
        {uploads.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Загруженные файлы
              </h2>
              <button
                onClick={() => setUploads([])}
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                Очистить
              </button>
            </div>

            <div className="space-y-2">
              {uploads.map((item) => (
                <div key={item.id} className="card px-4 py-3 flex items-center gap-3">
                  {/* Статус иконка */}
                  <div className="shrink-0">
                    {item.status === 'done' && <CheckCircle size={18} className="text-green-400" />}
                    {item.status === 'error' && <AlertCircle size={18} className="text-red-400" />}
                    {(item.status === 'pending' || item.status === 'uploading') && (
                      <div className="w-[18px] h-[18px] rounded-full border-2 border-surface-600 border-t-accent animate-spin" />
                    )}
                  </div>

                  {/* Инфо */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200 truncate">{item.file.name}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-slate-500">{formatSize(item.file.size)}</span>
                      {item.status === 'uploading' && (
                        <span className="text-xs text-accent-light">{item.progress}%</span>
                      )}
                      {item.status === 'done' && (
                        <span className="text-xs text-green-400 truncate">{item.message}</span>
                      )}
                      {item.status === 'error' && (
                        <span className="text-xs text-red-400 truncate">{item.error}</span>
                      )}
                    </div>
                    {item.status === 'uploading' && (
                      <div className="mt-1.5 h-0.5 bg-surface-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-accent rounded-full transition-all duration-200"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    )}
                  </div>

                  {/* Удалить */}
                  {(item.status === 'done' || item.status === 'error') && (
                    <button
                      onClick={() => removeUpload(item.id)}
                      className="text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                    >
                      <X size={15} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Индексация: кнопка и ссылка на Управление */}
        <div className="card p-4 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-start gap-3 flex-1">
            <FolderOpen size={18} className="text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-slate-200">Следующий шаг: индексация</p>
              <p className="text-xs text-slate-500 mt-1">
                После загрузки запустите индексацию — тогда ИИ сможет искать по документам. Всё делается кнопками, без консоли.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <StartIndexingButton />
            <Link
              to="/admin"
              className="text-xs text-slate-400 hover:text-accent-light transition-colors"
            >
              Управление →
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
