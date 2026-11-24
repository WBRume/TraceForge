import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const initializeRuntime = vi.fn()
const initializeFloatRuntime = vi.fn()
const loadRuntime = vi.fn()
const loadApp = vi.fn()
const loadFloatApp = vi.fn()

describe('application bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    initializeRuntime.mockReset().mockResolvedValue(undefined)
    initializeFloatRuntime.mockReset().mockResolvedValue(undefined)
    loadRuntime.mockReset()
    loadApp.mockReset()
    loadFloatApp.mockReset()
    delete window.sddDesktop
    delete window.sddTaskFloat
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    document.body.innerHTML = '<div id="app"></div>'
    vi.doMock('../../main', () => { loadApp(); return {} })
    vi.doMock('../taskFloatApp', () => { loadFloatApp(); return {} })
    vi.doMock('../initialize', () => {
      loadRuntime()
      return { initializeDesktopRuntime: initializeRuntime, initializeTaskFloatRuntime: initializeFloatRuntime }
    })
  })

  afterEach(() => {
    vi.doUnmock('../../main')
    vi.doUnmock('../taskFloatApp')
    vi.doUnmock('../initialize')
    delete window.sddDesktop
    delete window.sddTaskFloat
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    history.replaceState(null, '', location.pathname)
  })

  it.each(['web', 'electron'] as const)('loads %s without evaluating Tauri initialization', async runtime => {
    if (runtime === 'electron') {
      window.sddDesktop = { runtime: 'electron' } as NonNullable<Window['sddDesktop']>
    }
    await import('../../bootstrap')
    await vi.dynamicImportSettled()
    expect(loadApp).toHaveBeenCalledOnce()
    expect(loadRuntime).not.toHaveBeenCalled()
  })

  it('waits for Tauri IPC and HTTP initialization before evaluating application modules', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    let complete!: () => void
    initializeRuntime.mockReturnValue(new Promise<void>(resolve => { complete = resolve }))
    await import('../../bootstrap')
    await vi.waitFor(() => expect(initializeRuntime).toHaveBeenCalledOnce())
    expect(loadApp).not.toHaveBeenCalled()
    complete()
    await vi.dynamicImportSettled()
    expect(loadApp).toHaveBeenCalledOnce()
  })

  it.each(['electron', 'tauri'] as const)('mounts only the standalone preview in a %s task float', async runtime => {
    history.replaceState(null, '', '#/task-float?id=float-1&workspaceId=w1&taskId=t1')
    if (runtime === 'electron') window.sddTaskFloat = { close: vi.fn(), returnToClient: vi.fn(), drag: vi.fn() }
    else (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    await import('../../bootstrap')
    await vi.dynamicImportSettled()
    expect(loadApp).not.toHaveBeenCalled()
    expect(initializeRuntime).not.toHaveBeenCalled()
    expect(initializeFloatRuntime).toHaveBeenCalledTimes(runtime === 'tauri' ? 1 : 0)
    expect(loadFloatApp).toHaveBeenCalledOnce()
  })

  it('shows initialization failure without loading a partially configured Tauri application', async () => {
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    const error = new Error('IPC unavailable')
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    const ready = vi.fn()
    window.addEventListener('traceforge:app-ready', ready, { once: true })
    initializeRuntime.mockRejectedValue(error)
    await import('../../bootstrap')
    await vi.dynamicImportSettled()
    expect(loadApp).not.toHaveBeenCalled()
    expect(document.getElementById('app')?.textContent).toContain('桌面服务启动失败')
    expect(log).toHaveBeenCalledWith('Failed to initialize desktop runtime', error)
    expect(ready).toHaveBeenCalledOnce()
  })
})
