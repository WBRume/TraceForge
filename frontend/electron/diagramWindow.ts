import { app, BrowserWindow, globalShortcut, ipcMain, screen } from 'electron'
import type { IpcMainInvokeEvent, NativeImage } from 'electron'
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { DEFAULT_DIAGRAM_SHORTCUT, normalizeDiagramShortcut } from '../src/desktop/diagramShortcut'
import type { DiagramShortcutState } from '../src/types/diagramDesktop'

export function registerDiagramWindow(preload: string, rendererDir: string, devServerUrl?: string, icon?: NativeImage) {
  const userData = app.getPath('userData')
  const settingsPath = join(userData, 'diagram-shortcut')
  let window: BrowserWindow | null = null
  let loading: Promise<void> | null = null

  async function open() {
    if (loading) return loading
    if (window && !window.isDestroyed()) {
      if (window.isMinimized()) window.restore()
      window.show()
      window.focus()
      return
    }
    const { workArea } = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
    const width = Math.min(1340, workArea.width)
    const height = Math.min(880, workArea.height)
    const tool = new BrowserWindow({
      x: workArea.x + Math.round((workArea.width - width) / 2),
      y: workArea.y + Math.round((workArea.height - height) / 2),
      width, height, minWidth: Math.min(760, width), minHeight: Math.min(520, height),
      title: 'TraceForge · 绘图板',
      icon, show: false, backgroundColor: '#f8fafc', autoHideMenuBar: true,
      webPreferences: {
        preload, contextIsolation: true, nodeIntegration: false, sandbox: false,
        additionalArguments: ['--traceforge-diagram'],
      },
    })
    window = tool
    tool.removeMenu()
    tool.on('closed', () => { if (window === tool) window = null })
    tool.webContents.on('will-navigate', event => event.preventDefault())
    tool.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    const page = devServerUrl ? tool.loadURL(new URL('diagram.html', devServerUrl).href)
      : tool.loadFile(join(rendererDir, 'diagram.html'))
    loading = page.then(() => {
      if (!tool.isDestroyed()) { tool.show(); tool.focus() }
    }).catch(error => {
      if (!tool.isDestroyed()) tool.destroy()
      throw error
    }).finally(() => { loading = null })
    return loading
  }

  function register(accelerator: string) {
    try { return globalShortcut.register(accelerator, () => { void open().catch(console.error) }) }
    catch { return false }
  }

  let accelerator = DEFAULT_DIAGRAM_SHORTCUT
  try {
    accelerator = normalizeDiagramShortcut(readFileSync(settingsPath, 'utf8').trim()) ?? accelerator
  } catch { /* Use the default for a new profile. */ }
  let registered = register(accelerator)
  const state = (): DiagramShortcutState => ({ accelerator, registered })

  function requireClient(event: IpcMainInvokeEvent) {
    if (event.senderFrame !== event.sender.mainFrame || event.sender === window?.webContents) {
      throw new Error('Diagram launcher requires a client window')
    }
  }

  ipcMain.handle('sdd:diagram:open', (event) => { requireClient(event); return open() })
  ipcMain.handle('sdd:diagram:shortcut', (event) => { requireClient(event); return state() })
  ipcMain.handle('sdd:diagram:set-shortcut', (event, input: unknown) => {
    requireClient(event)
    const next = normalizeDiagramShortcut(input)
    if (!next) throw new Error('DIAGRAM_INVALID_SHORTCUT')
    if (next === accelerator && registered) return state()
    if (!register(next)) throw new Error('DIAGRAM_SHORTCUT_CONFLICT')
    const temporary = settingsPath + '.tmp'
    try {
      mkdirSync(userData, { recursive: true })
      writeFileSync(temporary, next, 'utf8')
      renameSync(temporary, settingsPath)
    } catch (error) {
      globalShortcut.unregister(next)
      try { rmSync(temporary, { force: true }) } catch { /* A later save can replace the temporary file. */ }
      throw error
    }
    if (registered) globalShortcut.unregister(accelerator)
    accelerator = next
    registered = true
    return state()
  })
  app.once('will-quit', () => { if (registered) globalShortcut.unregister(accelerator) })
}
