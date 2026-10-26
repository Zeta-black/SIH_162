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

// The dev server proxies the API so the browser stays same-origin: no CORS
// allowlist to maintain and no key handling in the frontend.
//
// `vite preview` is NOT given a proxy. It did not take effect when tried, and
// the frame-rate harness instead builds with VITE_API_BASE pointing at the API
// directly, which api.js already supports. One throwaway build using a
// documented escape hatch beats debugging preview's middleware.
const proxy = {
  '/api': { target: API_TARGET, changeOrigin: true },
  '/health': { target: API_TARGET, changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.FIRETRACE_WEB_PORT ?? 5173),
    proxy,
  },
  preview: {
    port: Number(process.env.FIRETRACE_PREVIEW_PORT ?? 4173),
  },
  build: { outDir: 'dist', sourcemap: false },
})
