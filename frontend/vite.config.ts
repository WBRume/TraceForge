import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { speechBuildOptions } from './desktop/speech/build-options.cjs'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 本地后端地址（与 deploy/docker/nginx/default.conf 的 /api、/ws 代理保持一致）
  const backendTarget = env.VITE_DEV_API_TARGET || 'http://localhost:8000'
  const desktopMode = process.env.TRACEFORGE_DESKTOP === '1'
  const speech = speechBuildOptions()
  const speechMode = speech.mode === 'offline' && !desktopMode ? 'off' : speech.mode

  return {
    define: { 'import.meta.env.VITE_SPEECH_MODE': JSON.stringify(speechMode) },
    base: desktopMode ? './' : '/',
    // Only the application entry is executable source. Rust/installer output also
    // contains HTML, including bundled pages that are expensive to scan again.
    optimizeDeps: {
      entries: ['index.html'],
    },
    plugins: [
      {
        name: 'desktop-offline-fonts',
        enforce: 'pre',
        transform(source, id) {
          if (!desktopMode || !/\.(vue|css)(?:\?|$)/.test(id)) return
          // A failed remote @import makes WebView2 reject lazy route CSS entirely.
          // Desktop development and builds use the existing system font fallbacks.
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
      watch: {
        ignored: ['**/src-tauri/target/**', '**/src-tauri/binaries/**', '**/release/**', '**/dist-electron/**', '**/dist-desktop-host/**'],
      },
      // Prepare the application modules while the Electron main process builds.
      warmup: desktopMode ? {
        clientFiles: ['./src/main.ts', './src/views/PortalView.vue'],
      } : undefined,
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
