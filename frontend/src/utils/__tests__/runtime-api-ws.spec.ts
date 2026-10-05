import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import api, { buildApiBaseUrl, getApiServerUrl, setApiServerUrl } from '@/utils/api'
import { isElectron } from '@/utils/runtime'
import { buildBackendWsUrl } from '@/utils/ws'
import type { SddDesktopApi } from '@/types/sddDesktop'

const desktopWindow = window as Window & { sddDesktop?: SddDesktopApi }

describe('runtime and backend URL helpers', () => {
  beforeEach(() => { setActivePinia(createPinia()) })
  afterEach(() => {
    delete desktopWindow.sddDesktop
    setApiServerUrl('http://localhost:8000')
  })

  it('detects Electron only when preload exposes sddDesktop', () => {
    expect(isElectron()).toBe(false)
    desktopWindow.sddDesktop = {} as SddDesktopApi
    expect(isElectron()).toBe(true)
  })

  it('normalizes API base URL', () => {
    expect(buildApiBaseUrl('http://localhost:8000/')).toBe('http://localhost:8000/api')
    setApiServerUrl('https://sdd.example.com/')
    expect(api.defaults.baseURL).toBe('https://sdd.example.com/api')
    expect(getApiServerUrl()).toBe('https://sdd.example.com')
  })

  it.each(['web', 'electron', 'tauri'] as const)('marks requests from %s using the native bridge', async (runtime) => {
    if (runtime !== 'web') desktopWindow.sddDesktop = { runtime } as SddDesktopApi
    const response = await api.post('/workspaces/ws/tasks', {}, {
      headers: { 'X-TraceForge-Client': 'desktop' },
      adapter: async config => ({ data: config.headers.get('X-TraceForge-Client'), status: 200,
        statusText: 'OK', headers: {}, config }),
    })
    expect(response.data).toBe(runtime === 'web' ? 'web' : 'desktop')
  })

  it('builds websocket URLs from the current API base', () => {
    setApiServerUrl('https://sdd.example.com')
    expect(buildBackendWsUrl('/ws/task/task-1')).toBe('wss://sdd.example.com/ws/task/task-1')
    expect(buildBackendWsUrl('/ws/api-mock/project-1', { token: 'token-1' })).toBe(
      'wss://sdd.example.com/ws/api-mock/project-1?token=token-1',
    )
  })
})
