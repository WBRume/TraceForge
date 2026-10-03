import { run } from '@tauri-apps/cli'
import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const args = process.argv.slice(2)

try {
  await run(['build', ...args], 'npm run tauri --')
  if (!args.some(arg => ['--no-bundle', '--help', '-h'].includes(arg))) {
    const metadata = JSON.parse(execFileSync('cargo', ['metadata', '--no-deps', '--format-version', '1'], {
      cwd: join(frontend, 'src-tauri'), encoding: 'utf8', windowsHide: true,
    }))
    const target = args.find(arg => arg.startsWith('--target='))?.slice('--target='.length)
      ?? (args.includes('--target') ? args[args.indexOf('--target') + 1]
        : args.includes('-t') ? args[args.indexOf('-t') + 1] : '')
    const profile = args.includes('--debug') || args.includes('-d') ? 'debug' : 'release'
    const bundle = join(metadata.target_directory, target || '', profile, 'bundle')
    const output = join(frontend, 'release', 'tauri')
    const { productName, version } = JSON.parse(readFileSync(join(frontend, 'package.json'), 'utf8'))
    let copied = 0
    mkdirSync(output, { recursive: true })
    for (const format of ['nsis', 'msi', 'dmg', 'macos', 'appimage', 'deb', 'rpm']) {
      const directory = join(bundle, format)
      if (!existsSync(directory)) continue
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        if (!entry.isFile() || !entry.name.toLowerCase().startsWith(productName.toLowerCase())
          || !entry.name.includes(version) || !/\.(exe|msi|dmg|AppImage|deb|rpm|gz|sig)$/i.test(entry.name)) continue
        copyFileSync(join(directory, entry.name), join(output, entry.name))
        console.log(`Tauri installer: ${join(output, entry.name)}`)
        copied++
      }
    }
    if (!copied) throw new Error(`No Tauri installers found in ${bundle}`)
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
