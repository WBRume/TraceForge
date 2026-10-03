/// <reference lib="dom" />

import { contextBridge, ipcRenderer } from 'electron'
import { createDesktopApi } from '../desktop/api'

// DOM events cross the isolated preload boundary without exposing window controls.
window.addEventListener('traceforge:app-ready', () => {
  ipcRenderer.send('traceforge:app-ready')
}, { once: true })

contextBridge.exposeInMainWorld('sddDesktop', createDesktopApi({
  runtime: 'electron',
  platform: process.platform,
  invoke: (channel, payload) => ipcRenderer.invoke(channel, payload),
  subscribe: (channel, listener) => {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => listener(payload)
    ipcRenderer.on(channel, wrapped)
    return () => { ipcRenderer.removeListener(channel, wrapped) }
  },
}))
