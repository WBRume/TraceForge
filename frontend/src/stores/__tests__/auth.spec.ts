import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

const desktopMock = vi.hoisted(() => ({
  config: {
    getConfig: vi.fn(),
    setConfig: vi.fn(),
  },
}))

vi.mock('@/utils/runtime', () => ({
  getSddDesktop: () => desktopMock,
  isElectron: () => true,
}))

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
  },
}))

vi.mock('@/router', () => ({
  default: { push: vi.fn() },
}))

/**
 * 回归：登出必须同步清理 Electron 桌面端持久化 token（config.json），
 * 否则刷新 / 重启（initializeApiFromDesktopConfig）与 loadLocalConfig
 * 会把旧 token 恢复回来 —— 表现为"点击登出没有用，刷新又登录"。
 */
describe('auth store logout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    desktopMock.config.setConfig.mockResolvedValue({
      serverUrl: 'http://localhost:8000',
      token: null,
      onboardingCompleted: false,
      repoMappings: {},
    })
  })

  const seedSession = (store: ReturnType<typeof useAuthStore>) => {
    store.setToken('token-abc')
    expect(localStorage.getItem('sdd_token')).toBe('token-abc')
  }

  it('logout clears localStorage token and the persisted desktop token', async () => {
    const store = useAuthStore()
    seedSession(store)

    store.logout()

    expect(store.token).toBeNull()
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem('sdd_token')).toBeNull()
    await vi.waitFor(() => {
      expect(desktopMock.config.setConfig).toHaveBeenCalledWith({ token: null })
    })
  })

  it('clearSession also clears the persisted desktop token', async () => {
    const store = useAuthStore()
    seedSession(store)

    store.clearSession()

    expect(store.token).toBeNull()
    expect(localStorage.getItem('sdd_token')).toBeNull()
    await vi.waitFor(() => {
      expect(desktopMock.config.setConfig).toHaveBeenCalledWith({ token: null })
    })
  })

  it('desktop config write failures do not break logout', async () => {
    desktopMock.config.setConfig.mockRejectedValue(new Error('ipc failed'))
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const store = useAuthStore()
    seedSession(store)

    store.logout()

    expect(store.token).toBeNull()
    expect(localStorage.getItem('sdd_token')).toBeNull()
    await vi.waitFor(() => {
      expect(consoleError).toHaveBeenCalled()
    })
    consoleError.mockRestore()
  })
})
