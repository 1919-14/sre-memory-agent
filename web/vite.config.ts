import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies to the FastAPI backend so the frontend talks to the same origin
// in development and in production (where FastAPI serves this build from web/dist).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Server-Sent Events must not be buffered or the live activity panel will stall.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
})
