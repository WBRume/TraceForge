import { app, BrowserWindow, shell } from 'electron'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { registerDesktopCommands } from '../desktop/register'
import { registerAttentionWindow } from '../desktop/attention'
import { shutdownSpeech } from './ipc/speech'
import { shutdownLocalServices } from './ipc/localResources'
import { guardClosedOutputPipes } from '../desktop/stdio'
import { registerTaskFloats } from './taskFloats'
import { DETACHED_WINDOW_SIZE, MIN_WORKSPACE_SIZE, registerWorkspaceWindows, WINDOWS_TITLE_BAR, workspaceWindowBounds } from './workspaceWindows'
import { MAIN_WORKSPACE_WINDOW } from '../src/types/workspaceWindows'
import type { WindowPlacement, WindowPoint } from '../src/types/workspaceWindows'

guardClosedOutputPipes()

const __dirname = dirname(fileURLToPath(import.meta.url))
const devServerUrl = process.env.VITE_DEV_SERVER_URL
const preloadPath = join(__dirname, 'preload.js')
const appFile = join(__dirname, '../dist/index.html')

// 沿用已有配置目录，避免应用改名后丢失登录和本地资源配置。
const userDataPath = app.getPath('userData')
if (userDataPath === join(app.getPath('appData'), app.getName()) && !existsSync(join(userDataPath, 'config.json'))) {
  const legacyUserData = ['SDD Native', 'frontend']
    .map(name => join(app.getPath('appData'), name))
    .find(path => existsSync(join(path, 'config.json')))
  if (legacyUserData) app.setPath('userData', legacyUserData)
}

let mainWindow: BrowserWindow | null = null
let closeTaskFloats: () => void
let workspaceWindows: ReturnType<typeof registerWorkspaceWindows> | undefined
let quitting = false
let shutdownComplete = false

const createWindow = async (id = MAIN_WORKSPACE_WINDOW, placement?: WindowPlacement, position?: WindowPoint) => {
  const primary = id === MAIN_WORKSPACE_WINDOW
  const windowsShell = !!workspaceWindows
  const window = new BrowserWindow({
    show: false,
    ...(primary ? { width: 1440, height: 960 } : DETACHED_WINDOW_SIZE),
    minWidth: windowsShell ? MIN_WORKSPACE_SIZE.width : 1120,
    minHeight: windowsShell ? MIN_WORKSPACE_SIZE.height : 720,
    ...(windowsShell ? {
      titleBarStyle: 'hidden' as const,
      titleBarOverlay: WINDOWS_TITLE_BAR,
      ...workspaceWindowBounds(placement, position),
    } : {}),
    title: app.getName(),
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: preloadPath,
      additionalArguments: primary ? [] : ['--traceforge-workspace-window'],
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // Keep collaboration leases and task events alive while the user edits
      // in an IDE and this window is minimized or covered.
      backgroundThrottling: false,
    },
  })
  workspaceWindows?.track(id, window)
  if (windowsShell) window.removeMenu()
  registerAttentionWindow(window)
  if (primary) {
    mainWindow = window
    window.on('close', event => {
      if (!quitting && workspaceWindows?.hasDetachedWindows()) {
        event.preventDefault()
        app.quit()
      }
    })
    window.on('closed', () => {
      if (mainWindow === window) mainWindow = null
      closeTaskFloats()
    })
    window.webContents.on('did-start-navigation', ({ isMainFrame, isSameDocument }) => {
      if (isMainFrame && !isSameDocument) closeTaskFloats()
    })
  }

  let frameReady = false
  let appReady = false
  const showWindow = () => {
    if (!frameReady || !appReady || window.isDestroyed()) return
    if (placement?.maximized) window.maximize()
    window.show()
    if (devServerUrl && process.env.TRACEFORGE_DEVTOOLS === '1') {
      window.webContents.openDevTools({ mode: 'detach' })
    }
  }
  window.once('ready-to-show', () => {
    frameReady = true
    showWindow()
  })
  window.webContents.ipc.once('traceforge:app-ready', () => {
    appReady = true
    showWindow()
  })
  if (devServerUrl) {
    window.webContents.on('before-input-event', (event, input) => {
      if (input.type === 'keyDown' && input.key === 'F12') {
        event.preventDefault()
        window.webContents.toggleDevTools()
      }
    })
  }

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url).catch(console.error)
    return { action: 'deny' }
  })
  if (windowsShell) window.webContents.on('will-navigate', event => event.preventDefault())

  try {
    if (devServerUrl) await window.loadURL(devServerUrl)
    else await window.loadFile(appFile)
  } catch (error) {
    if (!window.isDestroyed()) window.destroy()
    throw error
  }
}

app.whenReady().then(async () => {
  registerDesktopCommands()
  if (process.platform === 'win32') workspaceWindows = registerWorkspaceWindows(app.getPath('userData'), createWindow, () => quitting)
  closeTaskFloats = registerTaskFloats(() => mainWindow, preloadPath, appFile, devServerUrl)
  await createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  void shutdownSpeech()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
app.on('before-quit', event => {
  if (shutdownComplete) return
  event.preventDefault()
  if (quitting) return
  quitting = true
  void Promise.allSettled([shutdownSpeech(), shutdownLocalServices(), workspaceWindows?.flush()]).finally(() => {
    shutdownComplete = true
    app.quit()
  })
})
