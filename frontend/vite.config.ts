import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Replaces the Figma Make configuration, which carried four sandbox-only
// plugins (site.json injection, error-overlay replay, refresh-boundary
// fallback, and the story kit route) that have no meaning outside Figma.
export default defineConfig({
  plugins: [react()],
  resolve: 
  {
    alias: 
    { 
      '@': path.resolve(__dirname, './src') 
    },
  },
  server: 
  {
    port: 5173,
    // The API is served by FastAPI on 8000. Proxying keeps the browser on one
    // origin in development, so cookies and relative URLs behave the same way
    // they will in production behind a single host.
    proxy: 
    {
      '/auth': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})