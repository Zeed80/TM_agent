import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { ApiError } from '../api/client'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { login, isLoading } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!username.trim() || !password) {
      setError('Введите логин и пароль')
      return
    }

    try {
      await login(username.trim(), password)
      navigate('/chat', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Неизвестная ошибка')
      }
    }
  }

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-4">
      {/* Фоновый паттерн */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-accent/5 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-blue-600/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm animate-slide-up">
        {/* Логотип */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-accent/10 border border-accent/20 mb-4">
            <Bot size={32} className="text-accent-light" />
          </div>
          <h1 className="text-xl font-bold text-slate-100">Ярослав</h1>
          <p className="text-sm text-slate-500 mt-1">Корпоративный ИИ-ассистент</p>
        </div>

        {/* Форма входа */}
        <div className="card p-6 shadow-xl shadow-black/30">
          <h2 className="text-base font-semibold text-slate-200 mb-5">Вход в систему</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Логин */}
            <div>
              <label htmlFor="username" className="block text-xs font-medium text-slate-400 mb-1.5">
                Логин
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input-field"
                placeholder="Введите логин"
                disabled={isLoading}
              />
            </div>

            {/* Пароль */}
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-slate-400 mb-1.5">
                Пароль
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPass ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-field pr-10"
                  placeholder="Введите пароль"
                  disabled={isLoading}
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Ошибка */}
            {error && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                <AlertCircle size={15} className="text-red-400 shrink-0 mt-0.5" />
                <p className="text-sm text-red-300">{error}</p>
              </div>
            )}

            {/* Кнопка */}
            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full justify-center py-2.5 mt-2"
            >
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Вход...
                </>
              ) : (
                'Войти'
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-600 mt-6">
          Производственное предприятие · Защищённое соединение
        </p>
      </div>
    </div>
  )
}
