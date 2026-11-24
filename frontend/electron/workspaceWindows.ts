import { BrowserWindow, ipcMain, screen } from 'electron'
import type { IpcMainInvokeEvent } from 'electron'
import { createWorkspaceWindows } from '../desktop/workspaceWindows'
import { MAIN_WORKSPACE_WINDOW } from '../src/types/workspaceWindows'
import type { WindowPlacement, WindowPoint } from '../src/types/workspaceWindows'

export const WINDOWS_TITLE_BAR = { color: '#edf2f8', symbolColor: '#334155', height: 46 }
export const MIN_WORKSPACE_SIZE = { width: 720, height: 520 }
export const DETACHED_WINDOW_SIZE = { width: 1320, height: 820 }

export function workspaceWindowBounds(placement?: WindowPlacement, position?: WindowPoint) {
  const desired = placement ?? (position && { x: position.x - 110, y: position.y - 18, ...DETACHED_WINDOW_SIZE })
  if (!desired) return {}
  const area = (placement ? screen.getDisplayMatching(placement) : screen.getDisplayNearestPoint(position!)).workArea
  const width = Math.max(MIN_WORKSPACE_SIZE.width, Math.min(area.width, Math.round(desired.width)))
  const height = Math.max(MIN_WORKSPACE_SIZE.height, Math.min(area.height, Math.round(desired.height)))
  return {
    width, height,
    x: Math.max(area.x, Math.min(area.x + area.width - width, Math.round(desired.x))),
    y: Math.max(area.y, Math.min(area.y + area.height - height, Math.round(desired.y))),
  }
}

export function registerWorkspaceWindows(
  storageDirectory: string,
  createWindow: (id: string, placement?: WindowPlacement, position?: WindowPoint) => Promise<void>,
  isQuitting: () => boolean,
) {
  const nativeWindows = new Map<string, BrowserWindow>()
  let windowOrder: string[] = []
  const find = (id: string) => nativeWindows.get(id)
  const model = createWorkspaceWindows({
    create: createWindow,
    destroy: id => find(id)?.destroy(),
    focus: id => {
      const window = find(id)
      if (window?.isMinimized()) window.restore()
      window?.focus()
    },
    restoreMain: placement => {
      const window = find(MAIN_WORKSPACE_WINDOW)
      if (!window) return
      if (window.isMaximized()) window.unmaximize()
      window.setBounds(workspaceWindowBounds(placement))
      if (placement.maximized) window.maximize()
    },
    pointer: () => {
      const cursor = screen.getCursorScreenPoint()
      for (const id of windowOrder) {
        const window = find(id)
        if (!window?.isVisible() || window.isMinimized()) continue
        const bounds = window.getBounds()
        if (cursor.x < bounds.x || cursor.x >= bounds.x + bounds.width || cursor.y < bounds.y || cursor.y >= bounds.y + bounds.height) continue
        const content = window.getContentBounds()
        const zoom = window.webContents.getZoomFactor()
        return { screen: cursor, windowId: id, local: { x: (cursor.x - content.x) / zoom, y: (cursor.y - content.y) / zoom } }
      }
      return { screen: cursor }
    },
    emit: (id, event, payload) => find(id)?.webContents.send(event, payload),
  }, storageDirectory)

  function requireWindow(event: IpcMainInvokeEvent) {
    const id = windowOrder.find(id => find(id)?.webContents === event.sender)
    if (!id || event.senderFrame !== event.sender.mainFrame) throw new Error('Workspace window command is not allowed')
    return id
  }

  ipcMain.handle('sdd:workspace-window:command', (event, command) => model.command(requireWindow(event), command))
  ipcMain.handle('sdd:workspace-window:strip', (event, strip) => model.setStrip(requireWindow(event), strip))
  ipcMain.handle('sdd:workspace-window:drag', (event, { tabId, phase }) => model.drag(requireWindow(event), tabId, phase))
  ipcMain.handle('sdd:workspace-window:move', (event, grab: WindowPoint) => {
    const window = find(requireWindow(event))!
    if (!grab || ![grab.x, grab.y].every(value => Number.isFinite(value) && value >= 0 && value <= 32768)) {
      throw new Error('Invalid workspace window grab point')
    }
    const cursor = screen.getCursorScreenPoint()
    if (window.isMaximized()) window.unmaximize()
    const bounds = window.getBounds()
    const content = window.getContentBounds()
    const zoom = window.webContents.getZoomFactor()
    const offsetX = Math.min(Math.round(grab.x * zoom), Math.max(0, content.width - 24))
    const offsetY = Math.round(grab.y * zoom)
    window.setPosition(cursor.x - offsetX + bounds.x - content.x, cursor.y - offsetY + bounds.y - content.y)
  })
  ipcMain.handle('sdd:workspace-window:control', (event, action) => {
    const window = find(requireWindow(event))!
    if (action === 'minimize') window.minimize()
    if (action === 'maximize') window.isMaximized() ? window.unmaximize() : window.maximize()
    if (action === 'close') window.close()
  })

  return {
    flush: model.flush,
    hasDetachedWindows: () => nativeWindows.size > 1,
    track(id: string, window: BrowserWindow) {
      nativeWindows.set(id, window)
      const raise = () => { windowOrder = [id, ...windowOrder.filter(candidate => candidate !== id)] }
      const geometry = () => model.geometry(id, { ...window.getNormalBounds(), maximized: window.isMaximized() })
      raise()
      window.on('focus', raise)
      window.on('move', geometry)
      window.on('resize', geometry)
      window.on('maximize', geometry)
      window.on('unmaximize', geometry)
      window.on('show', geometry)
      window.on('closed', () => {
        nativeWindows.delete(id)
        windowOrder = windowOrder.filter(candidate => candidate !== id)
        if (!isQuitting()) model.closed(id)
      })
    },
  }
}
