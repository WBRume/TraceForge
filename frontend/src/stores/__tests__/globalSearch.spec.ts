import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useGlobalSearchStore } from '../globalSearch'
import { useAuthStore } from '../auth'
import { searchApi } from '@/services/searchApi'

vi.mock('@/services/searchApi', () => ({
  searchApi: {
    capabilities: vi.fn(),
  },
}))

describe('globalSearch store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('manages open and close state properly', () => {
    const auth = useAuthStore()
    auth.token = 'mock-token'
    auth.user = { id: 'u1', username: 'test', email: 'test@example.com' } as any

    const searchStore = useGlobalSearchStore()
    searchStore.capabilities = {
      enabled: true,
      ready: true,
      hybrid_available: true,
    }

    expect(searchStore.enabled).toBe(true)
    expect(searchStore.isOpen).toBe(false)

    searchStore.openSearch()
    expect(searchStore.isOpen).toBe(true)

    searchStore.closeSearch()
    expect(searchStore.isOpen).toBe(false)

    searchStore.toggleSearch()
    expect(searchStore.isOpen).toBe(true)

    searchStore.toggleSearch()
    expect(searchStore.isOpen).toBe(false)
  })

  it('loads capabilities from searchApi and respects token generation', async () => {
    const auth = useAuthStore()
    auth.token = 'mock-token'
    auth.user = { id: 'u1', username: 'test', email: 'test@example.com' } as any

    const mockCapabilities = {
      enabled: true,
      ready: true,
      hybrid_available: false,
    }
    vi.mocked(searchApi.capabilities).mockResolvedValueOnce(mockCapabilities)

    const searchStore = useGlobalSearchStore()
    await searchStore.loadCapabilities()

    expect(searchApi.capabilities).toHaveBeenCalledTimes(1)
    expect(searchStore.capabilities.enabled).toBe(true)
    expect(searchStore.capabilities.ready).toBe(true)
    expect(searchStore.enabled).toBe(true)
  })

  it('does not open when disabled', () => {
    const searchStore = useGlobalSearchStore()
    expect(searchStore.enabled).toBe(false)

    searchStore.openSearch()
    expect(searchStore.isOpen).toBe(false)
  })
})
