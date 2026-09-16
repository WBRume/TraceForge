import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { useChatSubmissions } from '../useChatSubmissions'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const receipt = { id: 'r', task_id: 'a', client_message_id: 'c', content: 'prompt', status: 'PREPARING', version: 1 }
const setup = () => {
  const task = ref('a')
  return { task, model: useChatSubmissions({ workspaceId: () => 'w', taskId: () => task.value, userId: () => 'u' }) }
}
beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear() })

describe('durable chat submissions', () => {
  it('keeps a preparation bubble and busy state when switching away and back', async () => {
    const { task, model } = setup()
    vi.mocked(api.post).mockResolvedValue({ data: receipt })
    await model.send('a', 'c', 'prompt')
    task.value = 'b'
    expect(model.busy.value).toBe(false)
    task.value = 'a'
    expect(model.busy.value).toBe(true)
    expect(model.bubbles([])[0].content).toBe('prompt')
  })
  it('does not drop an unconfirmed send when REST has not seen it yet', async () => {
    const { model } = setup()
    vi.mocked(api.post).mockRejectedValue(new Error('connection lost'))
    expect(await model.send('a', 'c', 'prompt')).toBe(true)
    expect(model.busy.value).toBe(true)
    expect(model.current.value[0]?.status).toBe('UNKNOWN')
    expect(model.unconfirmedKeys()).toEqual(['c'])
  })
  it('ignores a stale preparation response after execution has completed', async () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'SUCCEEDED', version: 3 })
    model.put({ ...receipt, version: 1 })
    expect(model.busy.value).toBe(false)
    expect(model.current.value[0]?.status).toBe('SUCCEEDED')
    expect(model.current.value[0]?.version).toBe(3)
  })
  it('drops a lower-version receipt even when it arrives later', () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'EXECUTING', version: 2, chat_message_id: 'm' })
    model.put({ ...receipt, status: 'PREPARING', version: 1 })
    expect(model.current.value[0]?.status).toBe('EXECUTING')
    model.put({ ...receipt, status: 'SUCCEEDED', version: 3, chat_message_id: 'm' })
    expect(model.current.value[0]?.status).toBe('SUCCEEDED')
  })
  it('falls back to rank comparison for rows without versions', () => {
    const { model } = setup()
    model.put({ ...receipt, version: undefined, status: 'EXECUTING' })
    model.put({ ...receipt, version: undefined, status: 'PREPARING' })
    expect(model.current.value[0]?.status).toBe('EXECUTING')
  })
  it('merges a formal message with its receipt without duplicate bubbles', () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'EXECUTING', version: 2, chat_message_id: 'm' })
    const items = model.bubbles([{ id: 'm', content: 'prompt', client_message_id: 'c' }])
    expect(items).toHaveLength(1)
    expect(items[0].delivery_status).toBe('executing')
  })
  it('renders a pending bubble with the local creator profile and metadata', () => {
    const { model } = setup()
    model.put({ ...receipt, creator_id: 'u', status: 'SENDING', metadata: { participants: ['u'] } })
    const [bubble] = model.bubbles([], {
      creator_display_name: 'Alice', creator_is_workspace_expert: true, creator_avatar_svg: '<svg/>',
    })
    expect(bubble.creator_display_name).toBe('Alice')
    expect(bubble.creator_is_workspace_expert).toBe(true)
    expect(bubble.metadata).toEqual({ participants: ['u'] })
  })
  it('does not decorate a receipt owned by another member with the local profile', () => {
    const { model } = setup()
    model.put({ ...receipt, creator_id: 'other', status: 'SENDING' })
    const [bubble] = model.bubbles([], { creator_is_workspace_expert: true })
    expect(bubble.creator_is_workspace_expert).toBeUndefined()
  })
  it('shows a failure without keeping the task busy', () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'FAILED', error_message: 'snapshot failed' })
    expect(model.busy.value).toBe(false)
    expect(model.bubbles([])[0].delivery_error).toBe('snapshot failed')
  })
  it('retries an unknown receipt with the same key on demand', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('lost response'))
    const { model } = setup()
    await model.send('a', 'c', 'prompt', { expert_id: 'e' })
    expect(model.busy.value).toBe(true)
    vi.mocked(api.post).mockResolvedValue({ data: receipt })
    // 恢复协调器：UNKNOWN 回执不在快照中 → 用原幂等键重发
    await model.send('a', 'c', 'prompt', { expert_id: 'e' })
    expect(api.post).toHaveBeenLastCalledWith('/workspaces/w/tasks/a/chat-submissions', {
      client_message_id: 'c', content: 'prompt', metadata: { expert_id: 'e' },
    })
    expect(model.current.value).toHaveLength(1)
    expect(model.current.value[0]?.status).toBe('PREPARING')
  })
  it('removes an undone receipt and rejects late receipt events', () => {
    const { model } = setup()
    const row = { ...receipt, chat_message_id: 'm', status: 'FAILED', version: 2 }
    model.put(row)
    model.removeMessages('a', new Set(['m']))
    model.put(row)
    expect(model.bubbles([])).toHaveLength(0)
  })
  it('keeps the visible prompt until successful history has arrived', () => {
    const { model } = setup()
    model.put(receipt)
    model.put({ ...receipt, status: 'SUCCEEDED', chat_message_id: 'm', version: 2 })
    expect(model.bubbles([])[0].content).toBe('prompt')
    expect(model.bubbles([{ id: 'm', content: 'prompt' }])).toHaveLength(1)
    expect(model.bubbles([])).toHaveLength(0)
  })
  it('clears all receipts of the task on session invalidation', () => {
    const { model } = setup()
    model.put(receipt)
    model.clear('a')
    model.put({ ...receipt, status: 'FAILED', version: 2 })
    expect(model.bubbles([])).toHaveLength(0)
  })
})
