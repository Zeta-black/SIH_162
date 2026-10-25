import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser never talks to NASA directly. Every data request goes to the
// FastAPI backend, which holds the FIRMS key server-side. In development the
// proxy below keeps that single-origin so no CORS or key handling leaks into
// the frontend.
// The backend's address is configurable so the smoke gate can run the whole
// stack on its own ports without colliding with a dev server, while keeping
// every request same-origin through this proxy (no CORS, no key in the browser).
const API_TARGET = process.env.FIRETRACE_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.FIRETRACE_WEB_PORT ?? 5173),
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
