import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '@/utils/api'
import { useChatSubmissions } from '../useChatSubmissions'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const receipt = { id: 'r', task_id: 'a', client_message_id: 'c', content: 'prompt', status: 'PREPARING' }
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
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
    await model.refresh('a')
    expect(model.busy.value).toBe(true)
    expect(model.current.value[0]?.status).toBe('UNKNOWN')
  })
  it('ignores a stale preparation response after execution has completed', async () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'SUCCEEDED' })
    vi.mocked(api.get).mockResolvedValue({ data: { items: [receipt] } })
    await model.refresh('a')
    expect(model.busy.value).toBe(false)
    expect(model.current.value[0]?.status).toBe('SUCCEEDED')
  })
  it('merges a formal message with its receipt without duplicate bubbles', () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'EXECUTING', chat_message_id: 'm' })
    const items = model.bubbles([{ id: 'm', content: 'prompt', client_message_id: 'c' }])
    expect(items).toHaveLength(1)
    expect(items[0].delivery_status).toBe('executing')
  })
  it('shows a failure without keeping the task busy', () => {
    const { model } = setup()
    model.put({ ...receipt, status: 'FAILED', error_message: 'snapshot failed' })
    expect(model.busy.value).toBe(false)
    expect(model.bubbles([])[0].delivery_error).toBe('snapshot failed')
  })
  it('retries an unknown receipt with the same key after reloading the view', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('lost response'))
    await setup().model.send('a', 'c', 'prompt', { expert_id: 'e' })
    const { model } = setup()
    expect(model.busy.value).toBe(true)
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
    vi.mocked(api.post).mockResolvedValue({ data: receipt })
    await model.refresh('a')
    expect(api.post).toHaveBeenLastCalledWith('/workspaces/w/tasks/a/chat-submissions', {
      client_message_id: 'c', content: 'prompt', metadata: { expert_id: 'e' },
    })
    expect(model.current.value).toHaveLength(1)
    expect(model.current.value[0]?.status).toBe('PREPARING')
  })
  it('does not resurrect cleared receipts from an in-flight history request', async () => {
    const { model } = setup()
    let resolve!: (value: any) => void
    vi.mocked(api.get).mockReturnValue(new Promise(done => { resolve = done }))
    const refresh = model.refresh('a')
    model.clear('a')
    resolve({ data: { items: [receipt] } })
    await refresh
    expect(model.current.value).toHaveLength(0)
  })
  it('removes an undone receipt and rejects late receipt events', () => {
    const { model } = setup()
    const row = { ...receipt, chat_message_id: 'm', status: 'FAILED' }
    model.put(row)
    model.removeMessages('a', new Set(['m']))
    model.put(row)
    expect(model.bubbles([])).toHaveLength(0)
  })
  it('keeps the visible prompt until successful history has arrived', () => {
    const { model } = setup()
    model.put(receipt)
    model.put({ ...receipt, status: 'SUCCEEDED', chat_message_id: 'm' })
    expect(model.bubbles([])[0].content).toBe('prompt')
    expect(model.bubbles([{ id: 'm', content: 'prompt' }])).toHaveLength(1)
    expect(model.bubbles([])).toHaveLength(0)
  })
  it('clears an old active receipt deleted by another client', async () => {
    const { model } = setup()
    model.put(receipt)
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
    await model.refresh('a')
    expect(model.busy.value).toBe(false)
    expect(model.bubbles([])).toHaveLength(0)
  })
  it('preserves a newer acceptance when an earlier empty GET arrives late', async () => {
    const { model } = setup()
    let resolve!: (value: any) => void
    vi.mocked(api.get).mockReturnValue(new Promise(done => { resolve = done }))
    const refresh = model.refresh('a')
    model.put(receipt)
    resolve({ data: { items: [] } })
    await refresh
    expect(model.busy.value).toBe(true)
  })
})
