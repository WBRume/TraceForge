import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { searchApi } from '@/services/searchApi'
import { useAuthStore } from '@/stores/auth'
import GlobalSearchHost from '../GlobalSearchHost.vue'
import GlobalSearchTrigger from '../GlobalSearchTrigger.vue'

vi.mock('@/services/searchApi', () => ({ searchApi: { capabilities: vi.fn() } }))
vi.mock('../GlobalSearchDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../GlobalPinnedFloatsWidget.vue', () => ({ default: { template: '<div />' } }))

enableAutoUnmount(afterEach)
afterEach(() => vi.useRealTimers())

it.each([
  { mode: 'keyword only', configuration: { embedding_configured: false }, refreshOnOpen: false },
  { mode: 'configured vectors', configuration: { embedding_configured: true }, refreshOnOpen: true },
  { mode: 'legacy vector index', configuration: { hybrid_unavailable_reason: 'semantic_index_not_ready' }, refreshOnOpen: true },
])('refreshes capabilities without polling while idle ($mode)', async ({ configuration, refreshOnOpen }) => {
  vi.useFakeTimers()
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.mocked(searchApi.capabilities).mockResolvedValue({
    enabled: true, ready: true, hybrid_available: false, hybrid_unavailable_reason: 'embedding_not_configured',
    ...configuration,
  })
  const pinia = createPinia()
  useAuthStore(pinia).token = 'mock-token'
  const options = { global: { plugins: [pinia] } }
  mount(GlobalSearchHost, options)
  const trigger = mount(GlobalSearchTrigger, options)
  await flushPromises()

  expect(searchApi.capabilities).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(60_000)
  expect(searchApi.capabilities).toHaveBeenCalledOnce()

  await trigger.get('button').trigger('click')
  const callsAfterOpen = refreshOnOpen ? 2 : 1
  expect(searchApi.capabilities).toHaveBeenCalledTimes(callsAfterOpen)
  window.dispatchEvent(new Event('focus'))
  expect(searchApi.capabilities).toHaveBeenCalledTimes(callsAfterOpen + 1)
  window.dispatchEvent(new Event('traceforge-features-changed'))
  expect(searchApi.capabilities).toHaveBeenCalledTimes(callsAfterOpen + 2)
  window.dispatchEvent(new Event('sdd-server-changed'))
  expect(searchApi.capabilities).toHaveBeenCalledTimes(callsAfterOpen + 3)
})
