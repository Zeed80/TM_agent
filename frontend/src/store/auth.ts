import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '../types'
import { api, clearToken, setToken } from '../api/client'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean

  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,

      login: async (username, password) => {
        set({ isLoading: true })
        try {
          const data = await api.post<{
            access_token: string
            user: User
          }>('/auth/login', { username, password })

          setToken(data.access_token)
          set({ user: data.user, isAuthenticated: true, isLoading: false })
        } catch (err) {
          set({ isLoading: false })
          throw err
        }
      },

      logout: () => {
        clearToken()
        set({ user: null, isAuthenticated: false })
      },

      refreshUser: async () => {
        try {
          const user = await api.get<User>('/auth/me')
          set({ user, isAuthenticated: true })
        } catch {
          clearToken()
          set({ user: null, isAuthenticated: false })
        }
      },
    }),
    {
      name: 'enterprise-auth',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    },
  ),
)
