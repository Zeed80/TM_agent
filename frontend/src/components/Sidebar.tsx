import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  MessageSquare, Upload, Activity, Users,
  LogOut, ChevronLeft, ChevronRight, Bot, Terminal, Cpu, Settings
} from 'lucide-react'
import { useAuthStore } from '../store/auth'
import clsx from 'clsx'

const NAV_ITEMS = [
  { to: '/chat',   icon: MessageSquare, label: 'Чат с ИИ' },
  { to: '/upload', icon: Upload,        label: 'Документы' },
  { to: '/models', icon: Cpu,          label: 'Модели' },
  { to: '/status', icon: Activity,     label: 'Статус системы' },
]

const ADMIN_ITEMS = [
  { to: '/admin',   icon: Terminal, label: 'Управление' },
  { to: '/settings', icon: Settings, label: 'Настройки' },
  { to: '/users',   icon: Users,    label: 'Пользователи' },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <aside
      className={clsx(
        'flex flex-col bg-surface-900 border-r border-surface-700 transition-all duration-300 shrink-0',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      {/* Логотип */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-surface-700">
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
          <Bot size={18} className="text-accent-light" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-semibold text-slate-100 truncate leading-none">Ярослав</p>
            <p className="text-xs text-slate-500 truncate mt-0.5">ИТР-ассистент</p>
          </div>
        )}
      </div>

      {/* Навигация */}
      <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150',
                isActive
                  ? 'bg-accent/15 text-accent-light'
                  : 'text-slate-400 hover:bg-surface-800 hover:text-slate-200',
              )
            }
          >
            <Icon size={18} className="shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}

        {/* Разделитель для admin */}
        {user?.role === 'admin' && (
          <>
            <div className="my-2 border-t border-surface-700" />
            {ADMIN_ITEMS.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150',
                    isActive
                      ? 'bg-accent/15 text-accent-light'
                      : 'text-slate-400 hover:bg-surface-800 hover:text-slate-200',
                  )
                }
              >
                <Icon size={18} className="shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      {/* Профиль / Выход */}
      <div className="p-2 border-t border-surface-700 space-y-0.5">
        {!collapsed && user && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg">
            <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center shrink-0">
              <span className="text-xs font-bold text-accent-light">
                {user.username[0].toUpperCase()}
              </span>
            </div>
            <div className="overflow-hidden">
              <p className="text-xs font-medium text-slate-200 truncate">{user.username}</p>
              <p className="text-xs text-slate-500 capitalize">{user.role === 'admin' ? 'Администратор' : 'Пользователь'}</p>
            </div>
          </div>
        )}

        <button
          onClick={handleLogout}
          className={clsx(
            'flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium',
            'text-slate-400 hover:bg-red-500/10 hover:text-red-400 transition-colors duration-150',
          )}
          title="Выйти"
        >
          <LogOut size={18} className="shrink-0" />
          {!collapsed && <span>Выйти</span>}
        </button>

        {/* Кнопка сворачивания */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm
                     text-slate-500 hover:bg-surface-800 hover:text-slate-300 transition-colors"
          title={collapsed ? 'Развернуть' : 'Свернуть'}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          {!collapsed && <span>Свернуть</span>}
        </button>
      </div>
    </aside>
  )
}
