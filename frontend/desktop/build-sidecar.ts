import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { speechBuildOptions } from './speech/build-options.cjs'

const root = resolve(import.meta.dir, '..')
const target = process.env.TAURI_ENV_TARGET_TRIPLE || execFileSync('rustc', ['--print', 'host-tuple'], { encoding: 'utf8' }).trim()
const targets: Record<string, string> = {
  'x86_64-pc-windows-msvc': 'bun-windows-x64',
  'x86_64-unknown-linux-gnu': 'bun-linux-x64',
  'aarch64-unknown-linux-gnu': 'bun-linux-arm64',
  'x86_64-apple-darwin': 'bun-darwin-x64',
  'aarch64-apple-darwin': 'bun-darwin-arm64',
}
if (!targets[target]) throw new Error(`Unsupported desktop sidecar target: ${target}`)
mkdirSync(resolve(root, 'src-tauri/binaries'), { recursive: true })
const staging = resolve(root, '.verify/desktop-host')
const bundled = await Bun.build({
  define: { __OFFLINE_SPEECH__: JSON.stringify(speechBuildOptions().enabled) },
  entrypoints: [resolve(root, 'desktop/host.ts'), resolve(root, 'desktop/local-resource/worker.ts')],
  target: 'bun',
  outdir: staging,
  naming: '[name].js',
  minify: true,
  plugins: [{
    name: 'tauri-native-ports',
    setup(build) {
      build.onResolve({ filter: /desktop[\\/]native$/ }, () => ({
        path: resolve(root, 'desktop/tauri-native.ts'),
      }))
    },
  }],
})
if (!bundled.success) { console.error(bundled.logs); process.exit(1) }
// Flatten entrypoints before compiling so worker URLs are independent of monorepo paths.
const result = await Bun.build({
  entrypoints: [resolve(staging, 'host.js'), resolve(staging, 'worker.js')],
  minify: true,
  compile: {
    target: targets[target] as any,
    outfile: resolve(root, `src-tauri/binaries/traceforge-desktop-host-${target}${target.includes('windows') ? '.exe' : ''}`),
  },
})
if (!result.success) { console.error(result.logs); process.exit(1) }
console.log(`Built desktop sidecar for ${target}`)
