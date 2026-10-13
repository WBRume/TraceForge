// Electron supplies the native ports in development and Electron builds.
// The Bun sidecar build substitutes tauri-native.ts at this boundary only.
export { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
export { startLocalResourceService } from '../electron/localResourceService'
export { setNativeAttention } from './attention'
import { app } from 'electron'
import { shell as nativeShell } from 'electron'
export const openIdeUrl = (url: string) => {
  if (!url.startsWith('vscode://file/')) throw new Error('Invalid IDE URL')
  return nativeShell.openExternal(url)
}
export const speechResourcesPath = () => app.isPackaged ? process.resourcesPath : app.getAppPath()
