import { afterEach, describe, expect, it } from 'vitest'
import api, { buildApiBaseUrl, getApiServerUrl, setApiServerUrl } from '@/utils/api'
import { isElectron } from '@/utils/runtime'
import { buildBackendWsUrl } from '@/utils/ws'
import type { SddDesktopApi } from '@/types/sddDesktop'

const desktopWindow = window as Window & { sddDesktop?: SddDesktopApi }

describe('runtime and backend URL helpers', () => {
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

  it('builds websocket URLs from the current API base', () => {
    setApiServerUrl('https://sdd.example.com')
    expect(buildBackendWsUrl('/ws/task/task-1')).toBe('wss://sdd.example.com/ws/task/task-1')
    expect(buildBackendWsUrl('/ws/api-mock/project-1', { userId: 'u 1' })).toBe(
      'wss://sdd.example.com/ws/api-mock/project-1?userId=u+1',
    )
  })
})
