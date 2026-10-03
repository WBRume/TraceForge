import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const initializeRuntime = vi.fn()
const loadRuntime = vi.fn()
const loadApp = vi.fn()

describe('application bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    initializeRuntime.mockReset().mockResolvedValue(undefined)
    loadRuntime.mockReset()
    loadApp.mockReset()
    delete window.sddDesktop
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    document.body.innerHTML = '<div id="app"></div>'
    vi.doMock('../../main', () => { loadApp(); return {} })
    vi.doMock('../initialize', () => {
      loadRuntime()
      return { initializeDesktopRuntime: initializeRuntime }
    })
  })

  afterEach(() => {
    vi.doUnmock('../../main')
    vi.doUnmock('../initialize')
    delete window.sddDesktop
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
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
