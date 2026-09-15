import { effectScope, ref, nextTick } from 'vue'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { useGlobalSearch } from '../useGlobalSearch'
import { searchApi } from '@/services/searchApi'
vi.mock('@/services/searchApi', () => ({ searchApi: { query: vi.fn(), close: vi.fn().mockResolvedValue({}) } }))

afterEach(() => { vi.useRealTimers() })
describe('search lifecycle', () => {
  it('debounces, isolates late results, closes the ranking snapshot', async () => {
    vi.useFakeTimers()
    const scope = effectScope()
    const open = ref(true)
    const state = scope.run(() => useGlobalSearch(open))!
    let resolveOld!: (r: any) => void
    vi.mocked(searchApi.query).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    state.query.value = '旧查询'
    await nextTick(); await vi.advanceTimersByTimeAsync(300)
    state.query.value = '新查询'
    await nextTick()
    resolveOld({ items: [{ entity_key: 'old' }], session_cursor: 'old-session' })
    await Promise.resolve(); await nextTick()
    expect(state.items.value).toEqual([])
    expect(searchApi.close).toHaveBeenCalledWith('old-session')
    scope.stop()
  })
  it('does not query while composing or after close', async () => {
    vi.useFakeTimers()
    const scope = effectScope()
    const open = ref(true)
    const state = scope.run(() => useGlobalSearch(open))!
    state.composing.value = true; state.query.value = '中文输入'
    await nextTick(); await vi.advanceTimersByTimeAsync(500)
    expect(searchApi.query).not.toHaveBeenCalled()
    state.composing.value = false; open.value = false
    await nextTick(); await vi.advanceTimersByTimeAsync(500)
    expect(searchApi.query).not.toHaveBeenCalled()
    scope.stop()
  })
})
