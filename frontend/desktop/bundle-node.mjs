import { build } from 'vite'
import { builtinModules } from 'node:module'
import { basename, dirname, resolve } from 'node:path'

const [entry, output] = process.argv.slice(2)
if (!entry || !output) throw new Error('Usage: node desktop/bundle-node.mjs <entry.ts> <output.mjs>')
await build({
  configFile: false, logLevel: 'error',
  build: {
    outDir: dirname(resolve(output)), emptyOutDir: false, target: 'node22', minify: false,
    lib: { entry: resolve(entry), formats: ['es'], fileName: () => basename(output) },
    rollupOptions: { external: [...builtinModules, ...builtinModules.map(name => `node:${name}`)] },
  },
})
