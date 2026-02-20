import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    // В dev-режиме проксируем API-запросы к FastAPI
    // (при работе вне Docker для локальной разработки)
    proxy: {
      '/api': {
        target: 'http://api:8000',
        changeOrigin: true,
      },
    },
    hmr: {
      // HMR через nginx WebSocket-прокси
      clientPort: 443,
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
  },
})
