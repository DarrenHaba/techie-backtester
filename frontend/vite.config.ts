import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5177,
    proxy: {
      // Backend default 8103. Override via VITE_BACKEND_URL if 8103 is
      // wedged by Windows TIME_WAIT after a crash and you need to use
      // 8104 temporarily — see README "Sharp edges".
      '/api': process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8103',
      '/ws': {
        target: (process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8103').replace('http', 'ws'),
        ws: true,
      },
    },
  },
})
