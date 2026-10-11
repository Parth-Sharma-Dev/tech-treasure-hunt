import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backend = process.env.TTH_BACKEND_URL || 'http://127.0.0.1:8000'
const proxy = { '/api': backend, '/admin': backend, '/static': backend }
const previewAssetPaths: Plugin = {
  name: 'preview-production-assets',
  configurePreviewServer(server) {
    server.middlewares.use((request, _response, next) => {
      // Preview mounts dist at /; production mounts its assets through Django.
      request.url = request.url?.replace(/^\/static\/frontend\/assets\//, '/assets/')
      next()
    })
  },
}

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), previewAssetPaths],
  // Django serves the compiled assets beside the API on the same browser origin.
  base: command === 'build' ? '/static/frontend/' : '/',
  build: { assetsDir: 'assets', sourcemap: false, manifest: true },
  server: {
    port: 5173,
    strictPort: true,
    proxy,
  },
  preview: { proxy },
}))
