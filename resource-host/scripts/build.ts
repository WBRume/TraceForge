import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

const root = fileURLToPath(new URL('..', import.meta.url))
const iconPath = path.join(root, 'assets/icon.ico')
const trayBinPath = path.join(root, 'src/tray-bin.ts')
let trayBase64 = ''

// If on Windows, compile TrayController and embed it as Base64 into src/tray-bin.ts
if (process.platform === 'win32') {
  const csc = 'C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe'
  const trayCs = path.join(root, 'scripts/TrayController.cs')
  const tempTrayExe = path.join(os.tmpdir(), `tf-tray-build-${Date.now()}.exe`)
  if (fs.existsSync(csc) && fs.existsSync(trayCs)) {
    const cscArgs = [csc, '/target:winexe', '/optimize+', `/out:${tempTrayExe}`]
    if (fs.existsSync(iconPath)) {
      cscArgs.push(`/win32icon:${iconPath}`)
    }
    cscArgs.push(trayCs)
    const cscRes = Bun.spawnSync(cscArgs)
    if (cscRes.exitCode === 0) {
      trayBase64 = fs.readFileSync(tempTrayExe).toString('base64')
      console.log(`[Tray] Compiled and embedded tray binary (${(trayBase64.length / 1024).toFixed(1)} KB base64)`)
      try { fs.unlinkSync(tempTrayExe) } catch { }
    } else {
      console.warn(`[Tray] Failed to compile tray with csc`)
    }
  }
}

// Clean up any stray exe files in scripts directory
for (const stray of ['traceforge-tray.exe']) {
  const strayPath = path.join(root, 'scripts', stray)
  if (fs.existsSync(strayPath)) {
    try { fs.unlinkSync(strayPath) } catch { }
  }
}

// Ensure src/tray-bin.ts is always valid TypeScript
fs.writeFileSync(trayBinPath, `// Auto-generated during build\nexport const TRAY_EXE_BASE64 = '${trayBase64}'\n`)

const targets = process.argv.includes('--all')
  ? ['bun-windows-x64', 'bun-linux-x64', 'bun-linux-arm64', 'bun-darwin-arm64', 'bun-darwin-x64']
  : [`bun-${process.platform === 'win32' ? 'windows' : process.platform}-${process.arch}`]

for (const target of targets) {
  const isWindows = target.includes('windows')
  const name = 'traceforge-resource-host' + (isWindows ? '.exe' : '')
  const folder = path.join(root, 'dist', target.replace('bun-', ''))
  fs.mkdirSync(folder, { recursive: true })

  // Clean out any old separate helper executables from dist folder so only main exe remains
  for (const oldFile of ['traceforge-tray.exe', 'tray.ps1', 'icon.ico']) {
    const oldPath = path.join(folder, oldFile)
    if (fs.existsSync(oldPath)) fs.unlinkSync(oldPath)
  }

  console.log(`Building target: ${target}...`)
  const result = Bun.spawnSync([
    process.execPath,
    'build',
    '--compile',
    `--target=${target}`,
    '--minify',
    path.join(root, 'src/main.ts'),
    path.join(root, 'src/worker.ts'),
    '--outfile',
    path.join(folder, name)
  ], { stdout: 'inherit', stderr: 'inherit' })
  if (result.exitCode !== 0) process.exit(result.exitCode)

  // Patch PE resource metadata to replace "Bun" with "TraceForge Resource Host"
  if (isWindows && process.platform === 'win32') {
    const rceditCandidates = [
      path.join(root, '../frontend/node_modules/electron-winstaller/vendor/rcedit.exe'),
      path.join(root, 'scripts/vendor/rcedit.exe')
    ]
    const rcedit = rceditCandidates.find(p => fs.existsSync(p))
    if (rcedit) {
      const rceditArgs = [
        rcedit,
        path.join(folder, name),
        '--set-version-string', 'FileDescription', 'TraceForge Resource Host',
        '--set-version-string', 'ProductName', 'TraceForge Resource Host',
        '--set-version-string', 'InternalName', 'traceforge-resource-host',
        '--set-version-string', 'OriginalFilename', 'traceforge-resource-host.exe',
        '--set-version-string', 'CompanyName', 'TraceForge',
        '--set-version-string', 'LegalCopyright', 'Copyright (C) 2026 TraceForge Team'
      ]
      if (fs.existsSync(iconPath)) {
        rceditArgs.push('--set-icon', iconPath)
      }
      const editRes = Bun.spawnSync(rceditArgs)
      if (editRes.exitCode === 0) {
        console.log(`[PE Metadata] Successfully updated PE metadata for ${name}`)
      } else {
        console.warn(`[PE Metadata] Warning: rcedit failed with exit code ${editRes.exitCode}`)
      }
    }

    // Patch PE Subsystem from Console (3) to Windows GUI (2) so no black cmd window pops up
    try {
      const exeFullPath = path.join(folder, name)
      const buffer = fs.readFileSync(exeFullPath)
      const peOffset = buffer.readInt32LE(0x3C)
      const subsystemOffset = peOffset + 0x5C
      buffer.writeInt16LE(2, subsystemOffset) // 2 = IMAGE_SUBSYSTEM_WINDOWS_GUI
      fs.writeFileSync(exeFullPath, buffer)
      console.log(`[PE Subsystem] Patched subsystem to GUI (2) for ${name} - no console window on launch`)
    } catch (err) {
      console.warn(`[PE Subsystem] Warning: failed to patch subsystem: ${err}`)
    }
  }

  fs.copyFileSync(path.join(root, 'README.md'), path.join(folder, 'README.md'))
  fs.copyFileSync(path.join(root, 'host.example.json'), path.join(folder, 'host.example.json'))

  const files = fs.readdirSync(folder).filter(f => f !== 'SHA256SUMS')
  const checksums = files.map(file => {
    const digest = createHash('sha256').update(fs.readFileSync(path.join(folder, file))).digest('hex')
    return `${digest}  ${file}`
  }).join('\n') + '\n'
  fs.writeFileSync(path.join(folder, 'SHA256SUMS'), checksums)

  const tarEntries = Object.fromEntries(
    files.concat(['SHA256SUMS']).map(file => [file, fs.readFileSync(path.join(folder, file))])
  )
  await Bun.Archive.write(
    path.join(root, 'dist', `traceforge-resource-host-${target.replace('bun-', '')}.tar.gz`),
    tarEntries,
    { compress: 'gzip' }
  )
  console.log(`Standalone release created: ${folder}`)
}
