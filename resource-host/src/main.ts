import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { readJson, writeJson } from './filesystem'
import { startServer } from './server'
import type { Config } from './runtime'

import { TRAY_EXE_BASE64 } from './tray-bin'

// If launched from a terminal on Windows, attach output to parent console; if double-clicked, runs silently without cmd window
if (process.platform === 'win32') {
  try {
    const { dlopen, FFIType } = await import('bun:ffi')
    const kernel32 = dlopen('kernel32.dll', {
      AttachConsole: { args: [FFIType.u32], returns: FFIType.bool }
    })
    kernel32.symbols.AttachConsole(0xFFFFFFFF)
  } catch { }
}

const args = process.argv.slice(2)
if (args.includes('--help')) {
  console.log(`TraceForge Resource Host
Usage: traceforge-resource-host [options]
Options:
  --config <path>    Path to host.json configuration file (auto-discovered if omitted)
  --port <port>      Override port number
  --headless         Run without GUI monitoring panel or system tray
  --no-gui           Alias for --headless
  --help             Show this help message

Requires Git and a separately running OpenCode serve or DSH web/host. No Node.js, Bun or Python installation is needed.`)
  process.exit(0)
}

function resolveConfigFile(): string {
  const index = args.indexOf('--config')
  if (index >= 0 && args[index + 1]) {
    return path.resolve(args[index + 1])
  }

  const exeDir = path.dirname(process.execPath)
  const candidates = [
    path.join(exeDir, 'host.json'),
    path.resolve('host.json'),
    path.join(os.homedir(), '.traceforge', 'host.json')
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }

  let targetDir = path.join(os.homedir(), '.traceforge')
  try {
    fs.mkdirSync(targetDir, { recursive: true })
  } catch {
    targetDir = exeDir
  }
  const targetConfig = path.join(targetDir, 'host.json')
  const defaultStateRoot = path.join(targetDir, 'resource-host-data')
  fs.mkdirSync(defaultStateRoot, { recursive: true })
  const generatedToken = randomUUID().replace(/-/g, '') + randomUUID().replace(/-/g, '')
  const defaultConfig = {
    state_root: defaultStateRoot,
    allowed_roots: [],
    token: generatedToken,
    listen_host: '0.0.0.0',
    port: 4098
  }
  writeJson(targetConfig, defaultConfig)
  console.log(`[TraceForge] Auto-initialized configuration at: ${targetConfig}`)
  return targetConfig
}

function launchWindowsGui(url: string, token: string, stateRoot: string, pid: number) {
  // 1. Try embedded tray executable (auto-extracted to temp, no extra exe needed in dist)
  if (TRAY_EXE_BASE64 && TRAY_EXE_BASE64.length > 100) {
    try {
      const tempTrayPath = path.join(os.tmpdir(), 'traceforge-tray-v2.exe')
      const trayBuffer = Buffer.from(TRAY_EXE_BASE64, 'base64')
      if (!fs.existsSync(tempTrayPath) || fs.statSync(tempTrayPath).size !== trayBuffer.length) {
        fs.writeFileSync(tempTrayPath, trayBuffer)
      }
      const child = spawn(tempTrayPath, [
        '--url', url,
        '--token', token,
        '--state-root', stateRoot,
        '--pid', String(pid)
      ], { detached: true, stdio: 'ignore' })
      child.unref()
      return
    } catch { }
  }

  const exeDir = path.dirname(process.execPath)
  const scriptDir = typeof import.meta.dir === 'string' ? import.meta.dir : ''
  const trayExeCandidates = [
    path.join(exeDir, 'traceforge-tray.exe'),
    path.join(scriptDir, 'traceforge-tray.exe'),
    path.join(scriptDir, '../scripts/traceforge-tray.exe'),
    path.join(exeDir, 'scripts/traceforge-tray.exe')
  ]

  let trayExe: string | null = null
  for (const p of trayExeCandidates) {
    if (fs.existsSync(p)) { trayExe = p; break }
  }

  if (trayExe) {
    try {
      const child = spawn(trayExe, [
        '--url', url,
        '--token', token,
        '--state-root', stateRoot,
        '--pid', String(pid)
      ], { detached: true, stdio: 'ignore' })
      child.unref()
      return
    } catch { }
  }

  const psScriptCandidates = [
    path.join(exeDir, 'tray.ps1'),
    path.join(scriptDir, '../scripts/tray.ps1')
  ]
  let psScript: string | null = null
  for (const p of psScriptCandidates) {
    if (fs.existsSync(p)) { psScript = p; break }
  }

  if (psScript) {
    try {
      const child = spawn('powershell.exe', [
        '-WindowStyle', 'Hidden',
        '-ExecutionPolicy', 'Bypass',
        '-File', psScript,
        '-Url', url,
        '-Token', token,
        '-StateRoot', stateRoot,
        '-Pid', String(pid)
      ], { detached: true, stdio: 'ignore' })
      child.unref()
      return
    } catch { }
  }

  const edgePaths = [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
  ]
  for (const ep of edgePaths) {
    if (fs.existsSync(ep)) {
      try {
        const tempProfile = path.join(os.tmpdir(), 'traceforge-rh-edge-profile')
        const child = spawn(ep, [`--app=${url}`, `--user-data-dir=${tempProfile}`, '--window-size=1020,740'], { detached: true, stdio: 'ignore' })
        child.unref()
        return
      } catch { }
    }
  }

  try {
    spawn('cmd.exe', ['/c', 'start', url], { detached: true, stdio: 'ignore' }).unref()
  } catch { }
}

const configPath = resolveConfigFile()
const rawConfig = readJson(configPath) as Config
const portArgIndex = args.indexOf('--port')
if (portArgIndex >= 0 && args[portArgIndex + 1]) {
  rawConfig.port = parseInt(args[portArgIndex + 1], 10)
}

const running = await startServer({ ...rawConfig, roots_config_path: path.resolve(configPath) })
console.log(`TraceForge Resource Host listening at ${running.server.url}`)

const isHeadless = args.includes('--headless') || args.includes('--no-gui')
if (!isHeadless && process.platform === 'win32') {
  let guiUrl = running.server.url.toString().replace(/\/$/, '')
  try {
    const parsed = new URL(guiUrl)
    if (parsed.hostname === '0.0.0.0' || parsed.hostname === '::' || parsed.hostname === '[::]') {
      parsed.hostname = '127.0.0.1'
      guiUrl = parsed.toString().replace(/\/$/, '')
    }
  } catch { }
  launchWindowsGui(guiUrl, rawConfig.token, rawConfig.state_root, process.pid)
}

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, async () => {
    await running.close()
    process.exit(0)
  })
}
