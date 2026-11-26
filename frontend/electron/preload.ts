/// <reference lib="dom" />

import { contextBridge, ipcRenderer } from 'electron'
import { createDesktopApi } from '../desktop/api'
import type { TaskFloatWindowApi } from '../src/types/taskFloat'
import type { DiagramWindowApi } from '../src/types/diagramDesktop'

// DOM events cross the isolated preload boundary without exposing window controls.
window.addEventListener('traceforge:app-ready', () => {
  ipcRenderer.send('traceforge:app-ready')
}, { once: true })

if (process.argv.includes('--traceforge-diagram')) {
  contextBridge.exposeInMainWorld('sddDiagram', {
    save: request => ipcRenderer.invoke('sdd:download:save', request),
  } satisfies DiagramWindowApi)
} else if (process.argv.includes('--traceforge-task-float')) {
  contextBridge.exposeInMainWorld('sddTaskFloat', {
    close: () => ipcRenderer.invoke('sdd:task-float:finish', false),
    returnToClient: () => ipcRenderer.invoke('sdd:task-float:finish', true),
    drag: process.platform === 'linux' ? undefined : request => ipcRenderer.invoke('sdd:task-float:drag', request),
  } satisfies TaskFloatWindowApi)
} else {
  contextBridge.exposeInMainWorld('sddDesktop', createDesktopApi({
    runtime: 'electron',
    platform: process.platform,
    secondaryWorkspaceWindow: process.argv.includes('--traceforge-workspace-window'),
    invoke: (channel, payload) => ipcRenderer.invoke(channel, payload),
    subscribe: (channel, listener) => {
      const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown) => listener(payload)
      ipcRenderer.on(channel, wrapped)
      return () => { ipcRenderer.removeListener(channel, wrapped) }
    },
  }))
}
