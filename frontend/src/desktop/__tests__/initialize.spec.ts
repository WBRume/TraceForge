import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initializeDesktopRuntime } from '../initialize'
import { getSddDesktop, isDesktop, isElectron, isTauri } from '../../utils/runtime'
import axios from 'axios'

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn(), unlisten: vi.fn(), fetch: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: mocks.listen }))
vi.mock('@tauri-apps/plugin-http', () => ({ fetch: mocks.fetch }))

const originalAdapter = axios.defaults.adapter
const originalEnv = axios.defaults.env

describe('desktop runtime initialization', () => {
  beforeEach(() => {
    mocks.invoke.mockResolvedValue('win32')
    mocks.listen.mockResolvedValue(mocks.unlisten)
    delete window.sddDesktop
  })
  afterEach(() => {
    axios.defaults.adapter = originalAdapter
    axios.defaults.env = originalEnv
    window.dispatchEvent(new Event('beforeunload'))
    delete window.sddDesktop
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
  })
  const tauriWindow = () => { (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {} }

  it('keeps the web runtime and existing Electron preload untouched', async () => {
    await initializeDesktopRuntime()
    expect(getSddDesktop()).toBeNull()
    expect(mocks.invoke).not.toHaveBeenCalled()
    const electron = { runtime: 'electron' as const } as NonNullable<Window['sddDesktop']>
    window.sddDesktop = electron
    await initializeDesktopRuntime()
    expect(window.sddDesktop).toBe(electron)
    expect(isElectron()).toBe(true)
  })

  it('installs Tauri only after event listening is ready', async () => {
    tauriWindow()
    let ready!: (value: () => void) => void
    mocks.listen.mockReturnValue(new Promise(resolve => { ready = resolve }))
    const initializing = initializeDesktopRuntime()
    await vi.waitFor(() => expect(mocks.listen).toHaveBeenCalled())
    expect(window.sddDesktop).toBeUndefined()
    ready(mocks.unlisten)
    await initializing
    expect(isDesktop()).toBe(true)
    expect(isTauri()).toBe(true)
    expect(isElectron()).toBe(false)
    expect(window.sddDesktop?.platform).toBe('win32')
    expect(axios.defaults.adapter).toBe('fetch')
    await axios.defaults.env!.fetch!('https://server.example/api/status')
    expect(mocks.fetch).toHaveBeenCalledWith('https://server.example/api/status', undefined)
  })

  it('preserves sliced binary data and command errors across JSON IPC', async () => {
    tauriWindow()
    await initializeDesktopRuntime()
    await window.sddDesktop!.download.save({ suggestedName: 'data.bin', data: new Uint8Array([9, 0, 255, 8]).subarray(1, 3) })
    expect(mocks.invoke).toHaveBeenLastCalledWith('desktop_invoke', {
      channel: 'sdd:download:save', payload: { suggestedName: 'data.bin', data: [0, 255] },
    })
    mocks.invoke.mockRejectedValueOnce(new Error('Git unavailable'))
    await expect(window.sddDesktop!.git.getStatus('/repo')).rejects.toThrow('Git unavailable')
  })

  it('delivers streaming events once and stops immediately on unsubscribe', async () => {
    tauriWindow()
    await initializeDesktopRuntime()
    const dispatch = mocks.listen.mock.calls[0]![1]
    const listener = vi.fn()
    const unsubscribe = window.sddDesktop!.process.onCommandOutput(listener)
    const output = { runId: 'run', text: 'hello', stream: 'stdout', at: 'now' }
    dispatch({ payload: { channel: 'sdd:process:output', payload: output } })
    expect(listener).toHaveBeenCalledTimes(1)
    expect(listener).toHaveBeenCalledWith(output)
    unsubscribe()
    dispatch({ payload: { channel: 'sdd:process:output', payload: output } })
    expect(listener).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('beforeunload'))
    expect(mocks.unlisten).toHaveBeenCalledTimes(1)
  })
})
