import { defineConfig } from 'vite'
import { builtinModules } from 'node:module'
import { resolve } from 'node:path'
import { speechBuildOptions } from './desktop/speech/build-options.cjs'

const external = [
  'electron',
  'cross-spawn',
  ...builtinModules,
  ...builtinModules.map((name) => `node:${name}`),
]

export default defineConfig({
  define: { __OFFLINE_SPEECH__: JSON.stringify(speechBuildOptions().enabled) },
  build: {
    emptyOutDir: false,
    outDir: 'dist-electron',
    target: 'node22',
    lib: {
      entry: {
        main: resolve(__dirname, 'electron/main.ts'),
        preload: resolve(__dirname, 'electron/preload.ts'),
        localResourceService: resolve(__dirname, 'electron/localResourceService.ts'),
        localResourceWorker: resolve(__dirname, 'electron/localResourceWorker.ts'),
      },
      formats: ['es'],
      fileName: (_format, entryName) => `${entryName}.js`,
    },
    rollupOptions: {
      external,
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
      },
    },
  },
})
