// Electron supplies the native ports in development and Electron builds.
// The Bun sidecar build substitutes tauri-native.ts at this boundary only.
export { app, BrowserWindow, dialog, ipcMain, shell, utilityProcess } from 'electron'
export { setNativeAttention } from './attention'
import { app } from 'electron'
export const speechResourcesPath = () => app.isPackaged ? process.resourcesPath : app.getAppPath()
