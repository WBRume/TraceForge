// Electron supplies the native ports in development and Electron builds.
// The Bun sidecar build substitutes tauri-native.ts at this boundary only.
export { app, BrowserWindow, dialog, ipcMain, shell, utilityProcess } from 'electron'
