/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendTarget = env.VITE_BACKEND_TARGET || 'http://127.0.0.1:8001'

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': { target: backendTarget, changeOrigin: true },
        '/health': { target: backendTarget, changeOrigin: true },
        '/evaluate': { target: backendTarget, changeOrigin: true },
        '/static': { target: backendTarget, changeOrigin: true },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.{ts,tsx}'],
      pool: 'threads',
      maxWorkers: 1,
    },
  }
})
