import { app, BrowserWindow, shell } from 'electron'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { registerDesktopCommands } from '../desktop/register'

const __dirname = dirname(fileURLToPath(import.meta.url))
const devServerUrl = process.env.VITE_DEV_SERVER_URL

// 沿用已有配置目录，避免应用改名后丢失登录和本地资源配置。
const userDataPath = app.getPath('userData')
if (userDataPath === join(app.getPath('appData'), app.getName()) && !existsSync(join(userDataPath, 'config.json'))) {
  const legacyUserData = ['SDD Native', 'frontend']
    .map(name => join(app.getPath('appData'), name))
    .find(path => existsSync(join(path, 'config.json')))
  if (legacyUserData) app.setPath('userData', legacyUserData)
}

let mainWindow: BrowserWindow | null = null

const createWindow = async () => {
  const window = new BrowserWindow({
    show: false,
    width: 1440,
    height: 960,
    minWidth: 1120,
    minHeight: 720,
    title: app.getName(),
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })
  mainWindow = window
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null
  })

  let frameReady = false
  let appReady = false
  const showWindow = () => {
    if (!frameReady || !appReady) return
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
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  if (devServerUrl) {
    await window.loadURL(devServerUrl)
    return
  }

  await window.loadFile(join(__dirname, '../dist/index.html'))
}

app.whenReady().then(async () => {
  registerDesktopCommands()
  await createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
