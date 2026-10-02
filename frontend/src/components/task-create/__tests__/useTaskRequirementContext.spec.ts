import { describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { useTaskRequirementContext } from '../composables/useTaskRequirementContext'
const api = vi.hoisted(() => ({ get:vi.fn() }))
vi.mock('@/utils/api', () => ({ default:api }))
describe('requirement creation context', () => {
  it('ignores an older selection response and blocks parent requirements', async () => {
    const pending: Array<(value:unknown) => void> = []
    api.get.mockImplementation(() => new Promise((resolve) => pending.push(resolve)))
    const id = ref<string | undefined>('a')
    const scope = effectScope()
    const context = scope.run(() => useTaskRequirementContext(() => 'ws', () => id.value))!
    id.value = 'b'
    await flushPromises()
    pending[1]!({ data:{ requirement:{ id:'b', title:'Current', can_link_task:true, child_count:0 } } })
    await flushPromises()
    pending[0]!({ data:{ requirement:{ id:'a', title:'Stale', can_link_task:true, child_count:0 } } })
    await flushPromises()
    expect(context.requirement.value?.id).toBe('b')
    id.value = 'parent'
    await flushPromises()
    pending[2]!({ data:{ requirement:{ id:'parent', child_count:2, can_link_task:false } } })
    await flushPromises()
    expect(context.error.value).toBe(true)
    expect(context.requirement.value).toBeNull()
    id.value = undefined
    await flushPromises()
    expect(context.error.value).toBe(false)
    expect(context.loading.value).toBe(false)
    scope.stop()
  })
})
