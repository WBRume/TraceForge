import { effectScope, nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { useGuideSession } from '../diagnosis/useGuideSession'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const snapshot = (version = 1, task_id = 'task') => ({ task_id, version, active_phase: 'PROBE' })
beforeEach(() => vi.resetAllMocks())

it('synchronizes an observer through WS and reloads on reconnect without polling', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: snapshot() })
  const scope = effectScope()
  const options = { workspaceId: () => 'ws', taskId: () => 'task', enabled: () => true }
  const clients = scope.run(() => [useGuideSession(options), useGuideSession(options)])!
  await flushPromises()
  for (const client of clients) {
    client.onEvent('playbook.guide_updated', { task_id: 'task', snapshot: snapshot(4) })
    client.onEvent('playbook.guide_updated', { task_id: 'task', snapshot: snapshot(2) })
    expect(client.state.value?.version).toBe(4)
  }
  expect(api.get).toHaveBeenCalledTimes(2)
  vi.mocked(api.get).mockResolvedValue({ data: snapshot(6) })
  clients[1]!.onEvent('playbook.resync', { task_id: 'task' })
  await flushPromises()
  expect(clients[1]!.state.value?.version).toBe(6)
  scope.stop()
})

it('ignores late HTTP results after task switching', async () => {
  let finish!: (value: any) => void
  vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce({ data: snapshot(1, 'other') })
  const task = ref('task')
  const scope = effectScope()
  const client = scope.run(() => useGuideSession({ workspaceId: () => 'ws', taskId: () => task.value, enabled: () => true }))!
  task.value = 'other'
  await nextTick()
  await flushPromises()
  finish({ data: snapshot(20) })
  await flushPromises()
  expect(client.state.value?.task_id).toBe('other')
  scope.stop()
})

it('reuses uncertain commands and refreshes version conflicts', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: snapshot() })
  vi.mocked(api.post).mockRejectedValueOnce(new Error('network'))
    .mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: 'STATE_VERSION_CONFLICT' } } } })
  const scope = effectScope()
  const client = scope.run(() => useGuideSession({ workspaceId: () => 'ws', taskId: () => 'task', enabled: () => true }))!
  await flushPromises()
  await client.command('advance')
  vi.mocked(api.get).mockResolvedValue({ data: snapshot(3) })
  await client.command('advance')
  expect(vi.mocked(api.post).mock.calls[0]![1]).toEqual(vi.mocked(api.post).mock.calls[1]![1])
  expect(client.state.value?.version).toBe(3)
  expect(client.error.value).toBe('阶段状态已更新')
  scope.stop()
})

it('updates both clients with hypotheses and rejects prior-session events even with larger versions', async () => {
  const current = { ...snapshot(5), session_generation: 1, active_phase: 'HYPOTHESIZE', hypotheses: [] }
  vi.mocked(api.get).mockResolvedValue({ data: current })
  const scope = effectScope()
  const clients = scope.run(() => [0, 1].map(() => useGuideSession({
    workspaceId: () => 'ws', taskId: () => 'task', enabled: () => true, sessionGeneration: () => 1,
  })))!
  await flushPromises()
  const updated = { ...current, version: 6, hypotheses: [{ id: 'H1', claim: '缓存键缺租户' }] }
  for (const client of clients) {
    client.onEvent('playbook.guide_updated', { task_id: 'task', snapshot: updated })
    client.onEvent('playbook.guide_updated', { task_id: 'task', snapshot: { ...current, version: 99, session_generation: 0, active_phase: 'PROBE' } })
    expect(client.state.value?.active_phase).toBe('HYPOTHESIZE')
    expect(client.state.value?.hypotheses).toEqual(updated.hypotheses)
  }
  expect(api.get).toHaveBeenCalledTimes(2)
  scope.stop()
})
