import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
const electron = vi.hoisted(() => ({
  window: { on: vi.fn(), flashFrame: vi.fn(), setOverlayIcon: vi.fn(), isFocused: vi.fn(), isMinimized: vi.fn(), isDestroyed: vi.fn() },
  dock: { bounce: vi.fn(), cancelBounce: vi.fn(), setBadge: vi.fn() },
}))
vi.mock('electron', () => ({
  BrowserWindow: { fromWebContents: () => electron.window }, app: { dock: electron.dock }, nativeImage: { createFromBuffer: () => 'orange-dot' },
}))
import { setNativeAttention } from '../attention'
beforeEach(() => {
  vi.stubGlobal('process', { ...process, platform: 'win32' })
  electron.window.isDestroyed.mockReturnValue(false); electron.window.isFocused.mockReturnValue(false); electron.window.isMinimized.mockReturnValue(true)
})
afterEach(() => vi.unstubAllGlobals())
describe('native window attention', () => {
  it('flashes and overlays only a background window, then clears synchronously on focus', () => {
    setNativeAttention({} as any, { flash: true, hitlCount: 2 })
    expect(electron.window.flashFrame).toHaveBeenLastCalledWith(true)
    expect(electron.window.setOverlayIcon).toHaveBeenLastCalledWith('orange-dot', 'AI 等待人工确认')
    electron.window.on.mock.calls.find(([name]) => name === 'focus')![1]()
    expect(electron.window.flashFrame).toHaveBeenLastCalledWith(false)
    expect(electron.window.setOverlayIcon).toHaveBeenLastCalledWith(null, '')
  })
  it('checks native focus again even if the renderer requests flashing', () => {
    electron.window.isFocused.mockReturnValue(true); electron.window.isMinimized.mockReturnValue(false)
    setNativeAttention({} as any, { flash: true, hitlCount: 2 })
    expect(electron.window.flashFrame).toHaveBeenLastCalledWith(false)
    expect(electron.window.setOverlayIcon).toHaveBeenLastCalledWith(null, '')
  })
  it('uses one macOS bounce and clears its badge and bounce', () => {
    vi.stubGlobal('process', { ...process, platform: 'darwin' }); electron.dock.bounce.mockReturnValue(7)
    setNativeAttention({} as any, { flash: true, hitlCount: 1 }); setNativeAttention({} as any, { flash: true, hitlCount: 1 })
    expect(electron.dock.bounce).toHaveBeenCalledTimes(1); expect(electron.dock.setBadge).toHaveBeenLastCalledWith('●')
    setNativeAttention({} as any, { flash: false, hitlCount: 0 })
    expect(electron.dock.cancelBounce).toHaveBeenCalledWith(7); expect(electron.dock.setBadge).toHaveBeenLastCalledWith('')
  })
})
