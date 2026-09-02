import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8080,
    proxy: {
      // 本地开发：把 /api 代理到后端 FastAPI
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
