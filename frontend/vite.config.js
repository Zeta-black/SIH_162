import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser never talks to NASA directly. Every data request goes to the
// FastAPI backend, which holds the FIRMS key server-side. In development the
// proxy below keeps that single-origin so no CORS or key handling leaks into
// the frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
