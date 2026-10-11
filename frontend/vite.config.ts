import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backend = process.env.TTH_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  // Django serves the compiled assets beside the API on the same browser origin.
  base: command === 'build' ? '/static/frontend/' : '/',
  build: { assetsDir: 'assets', sourcemap: false, manifest: true },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
    },
  },
}))
