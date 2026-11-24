import { BrowserWindow, ipcMain, screen, shell } from 'electron'
import type { IpcMainInvokeEvent } from 'electron'
import { TASK_FLOAT_ROUTE } from '../src/types/taskFloat'
import type { DesktopFloatDrag, TaskFloatClosed, TaskFloatPlacement, TaskFloatPrepareRequest } from '../src/types/taskFloat'

const supportsWindowOpacity = process.platform === 'win32' || process.platform === 'darwin'

interface NativeFloat {
  window: BrowserWindow
  detached: boolean
  outcome: Omit<TaskFloatClosed, 'id'>
}

function hideTaskFloat(window: BrowserWindow) {
  if (!window.isVisible()) return
  // Clear the surface before the compositor can animate its last frame.
  if (supportsWindowOpacity) window.setOpacity(0)
  window.hide()
}

function destroyTaskFloat(window: BrowserWindow) {
  if (window.isDestroyed()) return
  hideTaskFloat(window)
  window.destroy()
}

export function registerTaskFloats(
  mainWindow: () => BrowserWindow | null,
  preload: string,
  appFile: string,
  devServerUrl: string | undefined,
) {
  const floats = new Map<string, NativeFloat>()

  const requireMain = (event: IpcMainInvokeEvent) => {
    const main = mainWindow()
    if (!main || event.sender !== main.webContents || event.senderFrame !== event.sender.mainFrame) {
      throw new Error('The task float command requires the main window')
    }
    return main
  }

  const senderFloat = (event: IpcMainInvokeEvent) => {
    if (event.senderFrame !== event.sender.mainFrame) return undefined
    return [...floats.values()].find(float => float.window.webContents === event.sender)
  }

  const restoreMain = () => {
    const main = mainWindow()
    if (main?.isMinimized()) main.restore()
    main?.show()
  }

  const finish = (float: NativeFloat, outcome: NativeFloat['outcome']) => {
    float.outcome = outcome
    destroyTaskFloat(float.window)
    if (outcome.action === 'returned') restoreMain()
  }

  ipcMain.handle('sdd:task-float:prepare', async (event, request: TaskFloatPrepareRequest) => {
    const main = requireMain(event)
    const { id, workspaceId, taskId, title, size } = request
    if (![id, workspaceId, taskId].every(value => typeof value === 'string' && /^[a-z0-9_-]{1,128}$/i.test(value))
      || typeof title !== 'string' || ![size?.width, size?.height].every(value => Number.isFinite(value) && value > 0 && value <= 16384)) {
      throw new Error('Invalid task float request')
    }
    if (floats.has(id)) return

    const zoom = main.webContents.getZoomFactor()
    const width = Math.max(1, Math.round(size.width * zoom))
    const height = Math.max(1, Math.round(size.height * zoom))
    const { x, y } = main.getContentBounds()
    const window = new BrowserWindow({
      x, y, width, height,
      minWidth: Math.min(width, 300),
      minHeight: Math.min(height, 200),
      useContentSize: true,
      frame: false,
      title: title || 'TraceForge 会话',
      alwaysOnTop: true,
      skipTaskbar: true,
      minimizable: false,
      maximizable: false,
      autoHideMenuBar: true,
      backgroundColor: '#ffffff',
      show: false,
      webPreferences: {
        preload,
        additionalArguments: ['--traceforge-task-float'],
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
        zoomFactor: zoom,
      },
    })
    window.removeMenu()
    const float: NativeFloat = { window, detached: false, outcome: { action: 'closed' } }
    floats.set(id, float)
    window.on('close', () => {
      if (float.detached) float.outcome = { action: 'dismissed' }
      hideTaskFloat(window)
    })
    window.on('closed', () => {
      floats.delete(id)
      if (!event.sender.isDestroyed()) event.sender.send('sdd:task-float:closed', { id, ...float.outcome } satisfies TaskFloatClosed)
    })
    window.webContents.on('render-process-gone', () => destroyTaskFloat(window))
    window.on('page-title-updated', event => event.preventDefault())
    window.webContents.on('will-navigate', event => event.preventDefault())
    window.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//i.test(url)) void shell.openExternal(url).catch(console.error)
      return { action: 'deny' }
    })
    const hash = `${TASK_FLOAT_ROUTE}?${new URLSearchParams({ id, workspaceId, taskId })}`
    try {
      if (devServerUrl) await window.loadURL(`${devServerUrl}#${hash}`)
      else await window.loadFile(appFile, { hash })
    } catch (error) {
      if (!window.isDestroyed()) destroyTaskFloat(window)
      throw error
    }
  })

  ipcMain.handle('sdd:task-float:place', (event, { id, position, dropped }: TaskFloatPlacement) => {
    const main = requireMain(event)
    const float = floats.get(id)
    if (!float) throw new Error('Task float is unavailable')
    const { window } = float
    if (!position) {
      hideTaskFloat(window)
      return
    }
    if (![position.x, position.y].every(value => Number.isFinite(value) && Math.abs(value) <= 32768)) {
      throw new Error('Invalid task float position')
    }
    const origin = main.getContentBounds()
    const zoom = main.webContents.getZoomFactor()
    let x = origin.x + Math.round(position.x * zoom)
    let y = origin.y + Math.round(position.y * zoom)
    if (dropped) {
      float.detached = true
      // Keep a reachable part of the title visible when dropped against the screen edge.
      const { width, height } = window.getBounds()
      const area = screen.getDisplayMatching({ x, y, width, height }).workArea
      const titleWidth = Math.min(width, area.width, 160)
      const titleHeight = Math.min(height, area.height, 42)
      x = Math.max(area.x + titleWidth - width, Math.min(x, area.x + area.width - titleWidth))
      y = Math.max(area.y, Math.min(y, area.y + area.height - titleHeight))
    }
    window.setPosition(x, y)
    if (!window.isVisible()) {
      if (supportsWindowOpacity) window.setOpacity(1)
      window.showInactive()
    }
  })

  ipcMain.handle('sdd:task-float:close', (event, { id }: { id: string }) => {
    requireMain(event)
    const float = floats.get(id)
    if (float) destroyTaskFloat(float.window)
  })

  ipcMain.handle('sdd:task-float:finish', (event, returnToClient: boolean) => {
    const float = senderFloat(event)
    if (float) finish(float, { action: returnToClient ? 'returned' : 'dismissed' })
  })

  ipcMain.handle('sdd:task-float:drag', (event, { grab, dropped }: DesktopFloatDrag) => {
    const float = senderFloat(event)
    if (!float?.detached) return
    if (!grab || ![grab.x, grab.y].every(value => Number.isFinite(value) && value >= 0 && value <= 32768)) {
      throw new Error('Invalid task float drag position')
    }
    const { window } = float
    const cursor = screen.getCursorScreenPoint()
    const zoom = window.webContents.getZoomFactor()
    const x = cursor.x - Math.round(grab.x * zoom)
    const y = cursor.y - Math.round(grab.y * zoom)

    const main = mainWindow()
    if (dropped && main?.isVisible() && !main.isMinimized()) {
      const client = main.getContentBounds()
      if (cursor.x >= client.x && cursor.x < client.x + client.width && cursor.y >= client.y && cursor.y < client.y + client.height) {
        const scale = main.webContents.getZoomFactor()
        finish(float, { action: 'returned', position: { x: (x - client.x) / scale, y: (y - client.y) / scale } })
        return
      }
    }
    const bounds = window.getBounds()
    const content = window.getContentBounds()
    window.setPosition(x + bounds.x - content.x, y + bounds.y - content.y)
  })

  return () => {
    for (const { window } of floats.values()) destroyTaskFloat(window)
  }
}
