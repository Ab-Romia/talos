import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        ws: true,
      },
      // Socket.IO (team-chat realtime). The backend mounts it at /socket.io.
      '/socket.io': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        ws: true,
      },
    },
  },
})
