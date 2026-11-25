import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
// Vitest's defineConfig is Vite's, plus the types of the `test` section below.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // HMR mode only: the proxy keeps the browser on one origin, so no CORS.
    proxy: {
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
