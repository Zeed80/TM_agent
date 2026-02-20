import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Users, UserPlus, Trash2, Shield, User, CheckCircle,
  XCircle, Loader2, AlertCircle, Eye, EyeOff, X
} from 'lucide-react'
import { api, ApiError } from '../api/client'
import type { User as UserType } from '../types'
import clsx from 'clsx'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'
import { useAuthStore } from '../store/auth'

interface CreateUserForm {
  username: string
  full_name: string
  email: string
  password: string
  role: 'admin' | 'user'
}

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<CreateUserForm>({
    username: '', full_name: '', email: '', password: '', role: 'user',
  })
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (data: CreateUserForm) => api.post<UserType>('/auth/users', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      onClose()
    },
    onError: (err) => {
      setError(err instanceof ApiError ? (err.detail ?? err.message) : String(err))
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!form.username || !form.password) {
      setError('Заполните обязательные поля')
      return
    }
    mutation.mutate(form)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="card w-full max-w-md p-6 shadow-2xl animate-slide-up">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-slate-100">Создать пользователя</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">Логин *</label>
              <input
                className="input-field"
                placeholder="username"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">Полное имя</label>
              <input
                className="input-field"
                placeholder="Иванов Иван Иванович"
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">Email</label>
              <input
                type="email"
                className="input-field"
                placeholder="user@enterprise.local"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">Пароль * (мин. 8 символов)</label>
              <div className="relative">
                <input
                  type={showPass ? 'text' : 'password'}
                  className="input-field pr-10"
                  placeholder="Минимум 8 символов, буква, цифра"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
                <button type="button" tabIndex={-1} onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                  {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1.5">Роль</label>
              <div className="flex gap-2">
                {(['user', 'admin'] as const).map((r) => (
                  <button
                    type="button"
                    key={r}
                    onClick={() => setForm({ ...form, role: r })}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all flex-1 justify-center',
                      form.role === r
                        ? 'bg-accent/15 border-accent/40 text-accent-light'
                        : 'bg-surface-700 border-surface-600 text-slate-400 hover:text-slate-200',
                    )}
                  >
                    {r === 'admin' ? <Shield size={14} /> : <User size={14} />}
                    {r === 'admin' ? 'Администратор' : 'Пользователь'}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
              <AlertCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost flex-1 justify-center">
              Отмена
            </button>
            <button type="submit" disabled={mutation.isPending} className="btn-primary flex-1 justify-center">
              {mutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />}
              Создать
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function UsersPage() {
  const qc = useQueryClient()
  const { user: me } = useAuthStore()
  const [showCreate, setShowCreate] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data: users = [], isLoading } = useQuery<UserType[]>({
    queryKey: ['users'],
    queryFn: () => api.get<UserType[]>('/auth/users'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/users/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      setDeletingId(null)
    },
  })

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-100">Пользователи</h1>
            <p className="text-sm text-slate-500 mt-1">Управление учётными записями</p>
          </div>
          <button onClick={() => setShowCreate(true)} className="btn-primary">
            <UserPlus size={15} />
            Добавить
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-slate-500" />
          </div>
        ) : (
          <div className="card divide-y divide-surface-700">
            {users.map((user) => (
              <div key={user.id} className="px-4 py-3 flex items-center gap-3">
                {/* Аватар */}
                <div className={clsx(
                  'w-9 h-9 rounded-lg flex items-center justify-center shrink-0',
                  user.role === 'admin' ? 'bg-amber-500/15' : 'bg-accent/10',
                )}>
                  {user.role === 'admin'
                    ? <Shield size={16} className="text-amber-400" />
                    : <User size={16} className="text-accent-light" />
                  }
                </div>

                {/* Инфо */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-slate-200">{user.username}</p>
                    {user.id === me?.id && (
                      <span className="text-xs text-slate-500">(вы)</span>
                    )}
                    <span className={clsx(
                      'text-xs px-1.5 py-0.5 rounded font-medium',
                      user.role === 'admin'
                        ? 'bg-amber-500/15 text-amber-400'
                        : 'bg-accent/10 text-accent-light',
                    )}>
                      {user.role === 'admin' ? 'Администратор' : 'Пользователь'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {user.full_name ?? user.email ?? '—'}
                    {' · '}
                    {format(new Date(user.created_at), 'd MMM yyyy', { locale: ru })}
                  </p>
                </div>

                {/* Статус */}
                <div className="shrink-0">
                  {user.is_active
                    ? <CheckCircle size={16} className="text-green-400" />
                    : <XCircle size={16} className="text-red-400" />
                  }
                </div>

                {/* Удалить (нельзя себя) */}
                {user.id !== me?.id && (
                  <button
                    onClick={() => setDeletingId(user.id)}
                    disabled={deleteMutation.isPending && deletingId === user.id}
                    className="btn-danger shrink-0 px-2 py-1"
                    title="Удалить пользователя"
                  >
                    {deleteMutation.isPending && deletingId === user.id
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Trash2 size={14} />
                    }
                  </button>
                )}
              </div>
            ))}

            {users.length === 0 && (
              <div className="py-8 text-center text-slate-500 text-sm">
                Нет пользователей
              </div>
            )}
          </div>
        )}

        {/* Подтверждение удаления */}
        {deletingId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="card p-6 max-w-sm w-full">
              <h3 className="text-base font-semibold text-slate-100 mb-2">Удалить пользователя?</h3>
              <p className="text-sm text-slate-400 mb-5">
                Все чаты и файлы пользователя будут удалены. Это действие необратимо.
              </p>
              <div className="flex gap-2">
                <button onClick={() => setDeletingId(null)} className="btn-ghost flex-1 justify-center">
                  Отмена
                </button>
                <button
                  onClick={() => deleteMutation.mutate(deletingId)}
                  className="flex-1 btn-primary bg-red-600 hover:bg-red-700 justify-center"
                >
                  Удалить
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
