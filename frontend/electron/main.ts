import { app, BrowserWindow, shell } from 'electron'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { registerConfigIpc } from './ipc/config'
import { registerDownloadIpc } from './ipc/download'
import { registerGitIpc } from './ipc/git'
import { registerOauthIpc } from './ipc/oauth'
import { registerPatchIpc } from './ipc/patch'
import { registerProcessIpc } from './ipc/process'
import { registerSystemIpc } from './ipc/system'

const __dirname = dirname(fileURLToPath(import.meta.url))
const devServerUrl = process.env.VITE_DEV_SERVER_URL

let mainWindow: BrowserWindow | null = null

const createWindow = async () => {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1120,
    minHeight: 720,
    title: 'SDD Native',
    backgroundColor: '#f8fafc',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  if (devServerUrl) {
    await mainWindow.loadURL(devServerUrl)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
    return
  }

  await mainWindow.loadFile(join(__dirname, '../dist/index.html'))
}

const registerIpc = () => {
  registerConfigIpc()
  registerDownloadIpc()
  registerGitIpc()
  registerOauthIpc()
  registerPatchIpc()
  registerProcessIpc()
  registerSystemIpc()
}

app.whenReady().then(async () => {
  registerIpc()
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
