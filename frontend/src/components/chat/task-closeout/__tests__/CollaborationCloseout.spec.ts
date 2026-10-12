import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import TaskCloseoutPanel from '../TaskCloseoutPanel.vue'
import CompleteCloseoutForm from '../CompleteCloseoutForm.vue'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
const calls = vi.hoisted(() => ({ complete: vi.fn(), fail: vi.fn() }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/composables/useTaskCloseout', () => ({ useTaskCloseout: () => ({ saving: ref(false), error: ref(''), completeTask: calls.complete, failTask: calls.fail }) }))
beforeEach(() => { vi.clearAllMocks(); calls.complete.mockResolvedValue({ status: 'DONE' }) })

it('requires explicit acknowledgment of the exact current cloud snapshot and invalidates older consent', async () => {
  const state = ref({ snapshot_id: 'snapshot-A' })
  const collaboration = { enabled: ref(true), loading: ref(false), state, phase: ref('READY'), busy: ref(false), driver: ref(false) } as unknown as LocalCollaboration
  const wrapper = shallowMount(TaskCloseoutPanel, { props: { show: true, mode: 'complete', workspaceId: 'ws', taskId: 'task', collaboration }, global: { stubs: { Teleport: true } } })
  const form = () => wrapper.findComponent(CompleteCloseoutForm)
  const payload = { completion_summary: 'Done', landing_method: 'AI_IMPLEMENTED' }
  expect(form().props('submissionBlocked')).toBe(true)
  form().vm.$emit('submit', payload, []); await flushPromises()
  expect(calls.complete).not.toHaveBeenCalled()
  await wrapper.find('input[type="checkbox"]').setValue(true)
  form().vm.$emit('submit', payload, []); await flushPromises()
  expect(calls.complete).toHaveBeenCalledWith('ws', 'task', { ...payload, confirmed_server_snapshot_id: 'snapshot-A' }, [])
  state.value = { snapshot_id: 'snapshot-B' }; await flushPromises()
  expect(form().props('submissionBlocked')).toBe(true)
  expect((wrapper.find('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
  wrapper.unmount()
})

describe('incomplete collaboration delivery', () => {
  it('keeps conflict recovery as a prerequisite even if a checkbox is manipulated', async () => {
    const collaboration = { enabled: ref(true), loading: ref(false), state: ref({ snapshot_id: 'snapshot-C' }), phase: ref('CONFLICT_PENDING'), busy: ref(false), driver: ref(false) } as unknown as LocalCollaboration
    const wrapper = shallowMount(TaskCloseoutPanel, { props: { show: true, mode: 'complete', workspaceId: 'ws', taskId: 'task', collaboration }, global: { stubs: { Teleport: true } } })
    expect(wrapper.find('input[type="checkbox"]').attributes('disabled')).toBeDefined()
    wrapper.findComponent(CompleteCloseoutForm).vm.$emit('submit', { completion_summary: 'Done', landing_method: 'AI_IMPLEMENTED' }, [])
    await flushPromises(); expect(calls.complete).not.toHaveBeenCalled(); wrapper.unmount()
  })
})
