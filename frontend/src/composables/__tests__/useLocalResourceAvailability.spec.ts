import { effectScope, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useLocalResourceAvailability } from '../chat/session/useLocalResourceAvailability'

describe('local resource availability', () => {
  it('blocks until online, follows transitions, and invalidates on disconnect or task switch', () => {
    const scope = effectScope()
    const task = ref({ id: 'a', execution_location: 'LOCAL' })
    const state = scope.run(() => useLocalResourceAvailability(() => task.value))!
    expect(state.blocked.value).toBe(true)
    state.receive({ task_id: 'a', status: 'online' })
    expect(state.blocked.value).toBe(false)
    state.receive({ task_id: 'a', status: 'offline' })
    expect(state.blocked.value).toBe(true)
    expect(state.label.value).toBe('本地资源离线')
    state.receive({ task_id: 'a', status: 'online' })
    state.disconnected('a')
    expect(state.blocked.value).toBe(true)
    state.receive({ task_id: 'a', status: 'online' })
    task.value = { id: 'b', execution_location: 'LOCAL' }
    state.receive({ task_id: 'a', status: 'online' })
    expect(state.blocked.value).toBe(true)
    state.receive({ task_id: 'b', status: 'online' })
    expect(state.blocked.value).toBe(false)
    task.value = { id: 'c', execution_location: 'SERVER' }
    expect(state.blocked.value).toBe(false)
    scope.stop()
  })
})
