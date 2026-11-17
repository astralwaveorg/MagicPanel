import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 7100,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/feed': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'server/app/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // Element Plus 全量引入是大头：拆成独立 chunk 利用浏览器缓存，
          // 主包（页面代码）变小、依赖升级时不invalidate全部缓存
          'vendor-element': ['element-plus'],
          // qrcode 单独拆：门户公开页扫码用，不与 sortablejs/js-yaml（管理端）
          // 连坐下载（2026-11-18 红队修复）
          'vendor-qrcode': ['qrcode'],
          'vendor-misc': ['sortablejs', 'js-yaml'],
        },
      },
    },
  },
})
