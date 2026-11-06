import { defineConfig } from 'vite'
import { builtinModules } from 'node:module'
import { resolve } from 'node:path'
import { speechBuildOptions } from './desktop/speech/build-options.cjs'

export default defineConfig({
  publicDir: false,
  define: { __OFFLINE_SPEECH__: JSON.stringify(speechBuildOptions().enabled) },
  resolve: { alias: [{ find: /(?:\.\.\/)+desktop\/native$/, replacement: resolve(import.meta.dirname, 'desktop/tauri-native.ts') }] },
  build: {
    outDir: 'dist-desktop-host',
    target: 'node22',
    minify: true,
    lib: {
      entry: {
        host: resolve(import.meta.dirname, 'desktop/host.ts'),
        localResourceService: resolve(import.meta.dirname, 'desktop/local-resource/server.ts'),
        localResourceWorker: resolve(import.meta.dirname, 'desktop/local-resource/worker.ts'),
      },
      formats: ['es'],
      fileName: (_format, entryName) => `${entryName}.js`,
    },
    rollupOptions: {
      external: [...builtinModules, ...builtinModules.map(name => `node:${name}`)],
      output: {
        entryFileNames: '[name].js', chunkFileNames: 'chunks/[name]-[hash].js',
        banner: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);",
      },
    },
  },
})
