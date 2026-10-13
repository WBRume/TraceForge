import { effectScope, ref, nextTick } from 'vue'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useGlobalSearch } from '../useGlobalSearch'
import { searchApi } from '@/services/searchApi'
vi.mock('@/services/searchApi', () => ({ searchApi: { query: vi.fn(), close: vi.fn().mockResolvedValue({}) } }))

beforeEach(() => { vi.mocked(searchApi.close).mockResolvedValue({} as any) })
afterEach(() => { vi.useRealTimers() })
describe('search lifecycle', () => {
  it('binds pagination to the selected workspace and discards late results after a scope change', async () => {
    vi.useFakeTimers()
    const owner = effectScope()
    const workspace = ref<string | undefined>('ws-a')
    const state = owner.run(() => useGlobalSearch(ref(true), workspace))!
    vi.mocked(searchApi.query).mockResolvedValueOnce({
      items: [], session_cursor: 'session-a', next_cursor: 'page-a',
    } as any)
    state.query.value = '连接池'
    await nextTick(); await vi.advanceTimersByTimeAsync(300)
    expect(searchApi.query).toHaveBeenLastCalledWith(expect.objectContaining({ workspace_id: 'ws-a' }), expect.any(AbortSignal))
    let resolvePage!: (result: any) => void
    vi.mocked(searchApi.query).mockImplementationOnce(() => new Promise(resolve => { resolvePage = resolve }))
    const pendingPage = state.execute(true)
    expect(searchApi.query).toHaveBeenLastCalledWith(expect.objectContaining({ workspace_id: 'ws-a', cursor: 'page-a' }), expect.any(AbortSignal))
    workspace.value = 'ws-b'
    await nextTick()
    expect(searchApi.close).toHaveBeenCalledWith('session-a')
    resolvePage({ items: [{ entity_key: 'old-workspace' }], session_cursor: 'late-a' })
    await pendingPage
    expect(state.items.value).toEqual([])
    expect(searchApi.close).toHaveBeenCalledWith('late-a')
    vi.mocked(searchApi.query).mockResolvedValue({ items: [], session_cursor: 'new' } as any)
    await vi.advanceTimersByTimeAsync(300)
    expect(searchApi.query).toHaveBeenLastCalledWith({ q: '连接池', retrieval: 'hybrid', type: 'all', workspace_id: 'ws-b' }, expect.any(AbortSignal))
    workspace.value = undefined
    await nextTick(); await vi.advanceTimersByTimeAsync(300)
    expect(searchApi.query).toHaveBeenLastCalledWith({ q: '连接池', retrieval: 'hybrid', type: 'all' }, expect.any(AbortSignal))
    owner.stop()
  })
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
