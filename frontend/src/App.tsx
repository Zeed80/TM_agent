import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { getToken } from './api/client'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import UploadPage from './pages/UploadPage'
import ModelsPage from './pages/ModelsPage'
import StatusPage from './pages/StatusPage'
import UsersPage from './pages/UsersPage'
import AdminPage from './pages/AdminPage'
import SettingsPage from './pages/SettingsPage'
import AppLayout from './components/AppLayout'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore()
  if (!isAuthenticated || !getToken()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

export default function App() {
  const { isAuthenticated, refreshUser } = useAuthStore()

  // При загрузке приложения — проверяем токен
  useEffect(() => {
    if (getToken()) {
      refreshUser()
    }
  }, [refreshUser])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="models" element={<ModelsPage />} />
          <Route path="status" element={<StatusPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
