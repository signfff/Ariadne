import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy /api to the FastAPI server so the browser sees one origin in dev.
// `selfHandleResponse: false` keeps the SSE stream flowing through untouched.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
