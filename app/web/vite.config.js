import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const target = 'http://127.0.0.1:7866'
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target, ws: true, changeOrigin: true },
      '/media': { target, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 800 },
})
