import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, shallowRef } from 'vue'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import type { CollaborationReviewDiff, CollaborationReviewScope, CollaborationState } from '@/types/collaboration'
import { useCollaborationReview, type CollaborationReview } from '../useCollaborationReview'

const remote = vi.hoisted(() => ({ reviewDiff: vi.fn(), object: vi.fn() }))
vi.mock('@/services/collaborationApi', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/collaborationApi')>(),
  collaborationApi: () => remote,
}))

function diff(scope: CollaborationReviewScope, id = 'result', running = false): CollaborationReviewDiff {
  return { scope, baseline_snapshot_id: 'start', cloud_snapshot_id: id, protocol_version: 2, repositories: [], files: [], running }
}

let wrapper: ReturnType<typeof mount>
function setup() {
  const taskId = shallowRef('task')
  const state = shallowRef<CollaborationState | null>(null)
  const receivedOnce = shallowRef(false)
  let query!: CollaborationReview
  wrapper = mount(defineComponent({
    setup() {
      query = useCollaborationReview({
        workspaceId: () => 'ws', taskId: () => taskId.value, userId: () => 'user',
        sessionVersion: () => [1, 1], state: () => state.value,
        participating: () => Boolean(state.value?.enabled), receivedOnce: () => receivedOnce.value,
      })
      return () => null
    },
  }), { global: { plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })] } })
  return { query, taskId, state, receivedOnce }
}

beforeEach(() => {
  vi.useFakeTimers()
  remote.reviewDiff.mockReset().mockImplementation(async scope => diff(scope))
  remote.object.mockReset()
})
afterEach(() => { wrapper.unmount(); vi.useRealTimers() })

describe('collaboration review queries', () => {
  it('loads scopes on demand, deduplicates in-flight reads, and stops fetching on close', async () => {
    const { query } = setup()
    expect(remote.reviewDiff).not.toHaveBeenCalled()
    const close = query.open()
    await flushPromises()
    expect(query.results.cumulative.diff?.scope).toBe('cumulative')
    expect(query.results.round.diff).toBeNull()
    await Promise.all([query.loadRound(), query.loadRound()])
    expect(remote.reviewDiff.mock.calls.map(([scope]) => scope)).toEqual(['cumulative', 'round'])
    await query.refresh()
    expect(remote.reviewDiff.mock.calls.map(([scope]) => scope)).toEqual(['cumulative', 'round', 'cumulative', 'round'])
    close()
    await query.refresh()
    expect(remote.reviewDiff).toHaveBeenCalledTimes(4)
  })

  it('ignores the old response when a result event or task change supersedes it', async () => {
    const { query, taskId } = setup()
    let finish!: (value: CollaborationReviewDiff) => void
    remote.reviewDiff.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    query.open()
    const signal = remote.reviewDiff.mock.calls[0]![1] as AbortSignal
    await query.refresh()
    expect(signal.aborted).toBe(true)
    finish(diff('cumulative', 'old'))
    await flushPromises()
    expect(query.results.cumulative.diff?.cloud_snapshot_id).toBe('result')

    let reject!: (error: Error) => void
    remote.reviewDiff.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const pending = query.refresh()
    taskId.value = 'another-task'
    expect(query.results.cumulative.diff).toBeNull()
    reject(new Error('stale failure'))
    await pending
    await flushPromises()
    expect(query.results.cumulative.error).toBe('')
  })

  it('refreshes both requested scopes when synchronization observes a new version and pins the one-time receipt', async () => {
    const { query, state, receivedOnce } = setup()
    query.open()
    await query.loadRound()
    remote.reviewDiff.mockClear().mockImplementation(async scope => diff(scope, 'new-result'))
    state.value = { enabled: true, snapshot_id: 'new-result', input_snapshot_id: 'new-input' } as CollaborationState
    await flushPromises()
    expect(query.results.cumulative.diff?.cloud_snapshot_id).toBe('new-result')
    expect(query.results.round.diff?.cloud_snapshot_id).toBe('new-result')
    expect(remote.reviewDiff.mock.calls.map(([scope]) => scope)).toEqual(['cumulative', 'round'])
    receivedOnce.value = true
    await flushPromises()
    remote.reviewDiff.mockClear()
    await query.refresh()
    expect(remote.reviewDiff.mock.calls.map(([scope]) => scope)).toEqual(['cumulative'])
  })

  it('loads a newer socket cut while synchronization is busy and deduplicates its state response', async () => {
    const { query, state } = setup()
    const previous = { state_version: 1, snapshot_id: 'first', input_snapshot_id: 'input', sync_phase: 'READY' } as CollaborationState
    state.value = previous
    query.open()
    await flushPromises()
    const newer = { ...previous, state_version: 2, snapshot_id: 'next' }
    remote.reviewDiff.mockClear().mockResolvedValueOnce(diff('cumulative', 'next'))
    query.onEvent({ task_id: 'another-task', ...newer })
    query.onEvent({ task_id: 'task', ...previous })
    await flushPromises()
    expect(remote.reviewDiff).not.toHaveBeenCalled()
    query.onEvent({ task_id: 'task', ...newer })
    await flushPromises()
    expect(query.results.cumulative.diff?.cloud_snapshot_id).toBe('next')
    state.value = newer
    await flushPromises()
    expect(remote.reviewDiff).toHaveBeenCalledTimes(1)
  })

  it('rechecks a running cut and keeps scope errors independent', async () => {
    const { query } = setup()
    remote.reviewDiff.mockResolvedValueOnce(diff('cumulative', 'start', true))
    query.open()
    remote.reviewDiff.mockRejectedValueOnce(new Error('round unavailable'))
    await query.loadRound()
    expect(query.results.round.error).toBe('round unavailable')
    expect(query.results.cumulative.error).toBe('')
    await vi.advanceTimersByTimeAsync(1000)
    expect(query.results.cumulative.diff?.running).toBe(false)
    expect(query.results.cumulative.diff?.cloud_snapshot_id).toBe('result')
    expect(query.results.round.error).toBe('round unavailable')
  })

  it('reads preview text directly from the published object', async () => {
    const { query } = setup()
    remote.object.mockResolvedValueOnce(new TextEncoder().encode('cloud text').buffer)
    await expect(query.readText('object')).resolves.toBe('cloud text')
    expect(remote.object).toHaveBeenCalledWith('object')
  })
})
