import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  resolve: { alias: { 'node:sqlite': fileURLToPath(new URL('./desktop/local-resource/tests/sqlite.ts', import.meta.url)) } },
  test: {
    include: ['desktop/local-resource/tests/**/*.test.ts', 'desktop/tests/ide.test.ts'],
    environment: 'node',
    setupFiles: ['./desktop/local-resource/platform-node.ts'],
    testTimeout: 60000,
    hookTimeout: 30000,
    maxWorkers: 2,
    minWorkers: 1,
    restoreMocks: true,
  },
})
