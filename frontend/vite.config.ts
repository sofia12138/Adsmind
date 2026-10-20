import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

/** 演示包不带仓库里写死的基础设施地址。正式构建不走这个插件。 */
function stripDemoInfraHints(): Plugin {
  return {
    name: 'strip-demo-infra-hints',
    transform(code, id) {
      if (!id.includes(`${path.sep}src${path.sep}`)) return null
      if (!code.includes('47.237.67.41')) return null
      return code.replaceAll('47.237.67.41', '远程数据库')
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), mode === 'demo' ? stripDemoInfraHints() : null].filter(Boolean),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    port: 4000,
    strictPort: true,
    allowedHosts: ['.ngrok-free.dev'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
