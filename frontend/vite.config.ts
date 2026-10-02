import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 本地后端地址（与 deploy/docker/nginx/default.conf 的 /api、/ws 代理保持一致）
  const backendTarget = env.VITE_DEV_API_TARGET || 'http://localhost:8000'
  const desktopBuild = process.env.TRACEFORGE_DESKTOP === '1'

  return {
    base: desktopBuild ? './' : '/',
    plugins: [
      {
        name: 'desktop-offline-fonts',
        enforce: 'pre',
        transform(source, id) {
          if (!desktopBuild || !/\.(vue|css)(?:\?|$)/.test(id)) return
          // A failed remote @import makes WebView2 reject lazy route CSS entirely.
          // Desktop builds use the existing system font fallbacks, including offline.
          const transformed = source.replace(/@import\s+url\(["']https:\/\/fonts\.googleapis\.com\/[^"']+["']\);?/g, '')
          return transformed === source ? undefined : transformed
        },
      },
      vue(),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true
        },
        '/ws': {
          target: backendTarget,
          ws: true,
          changeOrigin: true
        }
      }
    }
  }
})
