import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: the console runs on :5173 and proxies /api to the FastAPI service on :8000.
// Prod: `npm run build` writes dist/, which satyapan.api serves at /.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
