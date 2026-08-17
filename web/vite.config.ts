import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api to uvicorn so the page only ever uses same-origin
// paths: identical in development and in production, where uvicorn serves this
// build itself and there is no second origin to configure CORS for.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
