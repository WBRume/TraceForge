import { app, BrowserWindow, nativeImage, type WebContents } from 'electron'

const DOT = 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAQ0lEQVR4nGNgoBX4jwbI1kiSQTBFX+dxY8V4DSGkmaAhxGhGNoQs23G6YhgYQHEgUiUaKU5I6IbgAng14zOIaI2kAgAIQ9UYiv9fIgAAAABJRU5ErkJggg=='
const registered = new WeakSet<BrowserWindow>()
const bounceIds = new WeakMap<BrowserWindow, number>()

export function registerAttentionWindow(window: BrowserWindow) {
  if (registered.has(window)) return
  registered.add(window)
  const clear = () => {
    if (!window.isDestroyed()) { window.flashFrame(false); if (process.platform === 'win32') window.setOverlayIcon(null, '') }
    const bounce = bounceIds.get(window)
    if (bounce !== undefined) app.dock?.cancelBounce(bounce)
    bounceIds.delete(window)
    if (process.platform === 'darwin') app.dock?.setBadge('')
  }
  window.on('focus', clear)
  window.on('closed', clear)
}

export function setNativeAttention(sender: WebContents, payload: { flash: boolean; hitlCount: number }) {
  const window = BrowserWindow.fromWebContents(sender)
  if (!window || window.isDestroyed()) return { ok: false }
  registerAttentionWindow(window)
  const background = !window.isFocused() || window.isMinimized()
  const flash = Boolean(payload?.flash) && background
  const hitlCount = background ? Math.max(0, Math.min(99, Math.floor(Number(payload?.hitlCount) || 0))) : 0
  if (process.platform === 'darwin') {
    if (flash && !bounceIds.has(window)) bounceIds.set(window, app.dock?.bounce('critical') ?? -1)
    else if (!flash) { const id = bounceIds.get(window); if (id !== undefined) app.dock?.cancelBounce(id); bounceIds.delete(window) }
    app.dock?.setBadge(hitlCount ? '●' : '')
  } else window.flashFrame(flash)
  if (process.platform === 'win32') window.setOverlayIcon(hitlCount ? nativeImage.createFromBuffer(Buffer.from(DOT, 'base64')) : null, hitlCount ? 'AI 等待人工确认' : '')
  return { ok: true }
}
