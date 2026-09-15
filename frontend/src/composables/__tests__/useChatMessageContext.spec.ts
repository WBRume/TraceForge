import { effectScope } from 'vue'
import { describe, it, expect, vi } from 'vitest'
import { useChatMessageContext } from '../useChatMessageContext'
import { searchApi } from '@/services/searchApi'
vi.mock('@/services/searchApi', () => ({ searchApi: { context: vi.fn(), moreContext: vi.fn() } }))
describe('anchored history', () => {
  it('drops a previous task response after reset', async () => {
    const scope = effectScope()
    const context = scope.run(() => useChatMessageContext())!
    let resolve!: (r: any) => void
    vi.mocked(searchApi.context).mockImplementation(() => new Promise(r => { resolve = r }))
    const pending = context.load('w', 't', 'm')
    context.reset()
    resolve({ messages: [{ id: 'old-task' }] })
    expect(await pending).toBeNull()
    expect(context.context.value).toBeNull()
    expect(context.anchored.value).toBe(false)
    scope.stop()
  })
})
