import { effectScope, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDiagnosisPlaybook } from '../diagnosis/useDiagnosisPlaybook'
import api from '@/utils/api'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const snapshot = (task = 'task-1', version = 1) => ({ id: 'run-1', task_id: task, state_version: version, event_seq: version, run_epoch: 1, state: 'READY' })
beforeEach(() => vi.resetAllMocks())

describe('diagnosis playbook state', () => {
  it('isolates provider output by run and replaces streamed text with its final result', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [snapshot()] } })
    const scope = effectScope()
    const state = scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => 'task-1', enabled: () => true }))!
    await flushPromises()
    const event = { task_id: 'task-1', run_id: 'run-1', run_epoch: 1, call_id: 'call', provider_type: 'text', payload: { text: '证据' } }
    state.onEvent('playbook.agent_event', { ...event, run_id: 'other' })
    state.onEvent('playbook.agent_event', { ...event, run_epoch: 0 })
    expect(state.agentText.value).toBe('')
    state.onEvent('playbook.agent_event', event)
    state.onEvent('playbook.agent_event', { ...event, provider_type: 'result', payload: { result: '证据完整' } })
    expect(state.agentText.value).toBe('证据完整')
    scope.stop()
  })
  it('makes no requests for an unbound development task', async () => {
    const scope = effectScope()
    scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => 'task', enabled: () => false }))
    await flushPromises()
    expect(api.get).not.toHaveBeenCalled()
    scope.stop()
  })

  it('ignores an old task response after switching tasks', async () => {
    let finish!: (value: unknown) => void
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ data: { items: [snapshot('task-2')] } })
    const task = ref('task-1')
    const scope = effectScope()
    const state = scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => task.value, enabled: () => true }))!
    task.value = 'task-2'
    await nextTick()
    await flushPromises()
    finish({ data: { items: [snapshot('task-1')] } })
    await flushPromises()
    expect(state.run.value?.task_id).toBe('task-2')
    scope.stop()
  })

  it('applies observer events, deduplicates, and recovers a gap with a single request', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [snapshot()] } })
      .mockResolvedValueOnce({ data: { snapshot: snapshot('task-1', 4) } })
    const scope = effectScope()
    const state = scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => 'task-1', enabled: () => true }))!
    await flushPromises()
    const event = { task_id: 'task-1', run_id: 'run-1', run_epoch: 1, event_seq: 2, payload: { snapshot: snapshot('task-1', 2) } }
    state.onEvent('playbook.updated', event)
    state.onEvent('playbook.updated', event)
    expect(state.run.value?.state_version).toBe(2)
    state.onEvent('playbook.updated', { ...event, event_seq: 4, payload: {} })
    state.onEvent('playbook.updated', { ...event, event_seq: 4, payload: {} })
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(state.run.value?.state_version).toBe(4)
    scope.stop()
  })

  it('reuses the same command key after an unknown network result', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [snapshot()] } })
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network lost')).mockResolvedValueOnce({ data: snapshot('task-1', 2) })
    const scope = effectScope()
    const state = scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => 'task-1', enabled: () => true }))!
    await flushPromises()
    await state.command('continue')
    await state.command('continue')
    const first = vi.mocked(api.post).mock.calls[0]![1] as { idempotency_key: string }
    const retry = vi.mocked(api.post).mock.calls[1]![1] as { idempotency_key: string }
    expect(first.idempotency_key).toBe(retry.idempotency_key)
    scope.stop()
  })

  it('discovers a run attached by another collaborator without querying idle diagnosis tasks', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [snapshot()] } })
    const scope = effectScope()
    const state = scope.run(() => useDiagnosisPlaybook({ workspaceId: () => 'ws', taskId: () => 'task-1', enabled: () => false, eligible: () => true }))!
    await flushPromises()
    expect(api.get).not.toHaveBeenCalled()
    state.onEvent('playbook.created', { task_id: 'task-1', run_id: 'run-1', run_epoch: 1, event_seq: 1, payload: {} })
    await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(state.run.value?.id).toBe('run-1')
    scope.stop()
  })
})
