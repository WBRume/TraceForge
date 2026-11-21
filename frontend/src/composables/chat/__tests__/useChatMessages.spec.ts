import { describe, expect, it } from 'vitest'
import { useChatMessages } from '../message/useChatMessages'

const createMessages = (anchored = false) => {
  const hasNew = { value: false }
  const historyContext = {
    anchored: { value: anchored },
    hasNew,
  } as any
  const submissions = {
    bubbles: (list: any[]) => list,
  } as any
  const store = useChatMessages({
    submissions,
    historyContext,
    getWorkspaceId: () => 'w1',
    getCreatorMeta: () => ({ creator_id: 'u1' }),
  })
  return { store, hasNew, historyContext }
}

describe('useChatMessages', () => {
  it('grows each draft in place and preserves completed messages through replay and history', () => {
    const { store } = createMessages()
    const created_at = '2026-11-15T00:00:00Z'
    store.applyStream({ id: 'first', content: '第一', created_at })
    store.applyStream({ id: 'first', content: '第一段', created_at })
    store.applyStream({ id: 'second', content: '第二', created_at })
    expect(store.messages.value.map(message => [message.id, message.content])).toEqual([
      ['first', '第一段'], ['second', '第二'],
    ])

    const snapshot = store.captureIdentitySnapshot()
    store.applyStream({ id: 'second', content: '第二段', created_at })
    store.mergeSessionSnapshot([{ id: 'second', content: '第二段完成', streaming: false }], snapshot)
    store.upsert({ id: 'first', content: '第一段完成', streaming: false })
    store.applyStream({ id: 'first', content: '第一', created_at })
    store.applyStream({ id: 'second', content: null, created_at })
    expect(store.messages.value.map(message => message.content)).toEqual(['第一段完成', '第二段完成'])
    expect(store.messages.value.every(message => !message.streaming)).toBe(true)
  })

  it('merges upserts by client_message_id identity and moves refreshed result cards to the end', () => {
    const { store } = createMessages()
    store.upsert({ id: 'a', client_message_id: 'c1', content: 'v1' })
    store.upsert({ id: 'b', content: 'other' })
    // 相同身份（client_message_id）的回执合并进既有气泡（字段以后到为准）
    store.upsert({ id: 'a2', client_message_id: 'c1', content: 'v2' })
    expect(store.messages.value.map(item => item.client_message_id)).toEqual(['c1', undefined])
    expect(store.messages.value[0].content).toBe('v2')

    // 定位结果卡刷新后移到会话末尾
    store.upsert({ id: 'd1', message_type: 'diagnosis_result', content: 'first' })
    store.upsert({ id: 'b2', content: 'later' })
    store.upsert({ id: 'd1', message_type: 'diagnosis_result', content: 'refreshed' })
    const last = store.messages.value[store.messages.value.length - 1]
    expect(last.content).toBe('refreshed')
  })

  it('buffers new messages behind an anchored history window instead of appending', () => {
    const { store, hasNew, historyContext } = createMessages(false)
    store.upsert({ id: 'a', client_message_id: 'c1', content: 'old' })

    // 进入历史锚点窗口后：新消息只记「有新消息」，不再进列表
    historyContext.anchored.value = true
    store.upsert({ id: 'new-1', content: 'fresh' })
    expect(store.messages.value.map(item => item.id)).toEqual(['a'])
    expect(hasNew.value).toBe(true)
    // 相同身份的更新（回执合并）仍然允许写入
    store.upsert({ id: 'a2', client_message_id: 'c1', content: 'old-edited' })
    expect(store.messages.value.map(item => item.content)).toEqual(['old-edited'])
  })

  it('keeps messages that arrived during a reset history request', () => {
    const { store } = createMessages()
    store.upsert({ id: 'a', client_message_id: 'c1', content: 'sent-before' })

    // 请求发起前捕获快照（与 loadHistory 的时序一致）
    const snapshot = store.captureIdentitySnapshot()
    // 请求期间本地气泡对象被替换（如 delivery_status 更新）
    store.upsert({ id: 'a', client_message_id: 'c1', content: 'sent-during', delivery_status: 'sending' })

    store.applyHistoryPage([
      { id: 'h1', content: 'history-1' },
      { id: 'h2', content: 'history-2' },
    ], true, snapshot)

    expect(store.messages.value.map(item => item.id)).toEqual(['h1', 'h2', 'a'])
    expect(store.messages.value[2].content).toBe('sent-during')
  })

  it('removes by id set and records local sent times', () => {
    const { store } = createMessages()
    store.upsert({ id: 'a' })
    store.upsert({ id: 'b' })
    store.removeByIds(new Set(['a']))
    expect(store.messages.value.map(item => item.id)).toEqual(['b'])

    store.noteSentTime('c9')
    expect(store.visibleMessages.value).toEqual(store.messages.value)
  })

  it('keeps a pending confirmation through history reset and applies its private failure receipt', () => {
    const { store } = createMessages()
    store.upsert({
      id: 'local-answer', creator_id: 'u1', client_message_id: 'answer', content: 'my reply', delivery_status: 'processing',
      metadata: { interaction_id: 'interaction', reply_to_message_id: 'question' },
    })
    store.applyHistoryPage([{ id: 'question', content: 'Continue?' }], true)
    expect(store.pendingConfirmationKeys()).toEqual(['answer'])
    store.applyConfirmationReplies([{ client_message_id: 'answer', status: 'FAILED', error_message: 'Timed out' }])
    expect(store.findById('local-answer')).toMatchObject({
      content: 'my reply', delivery_status: 'failed', delivery_error: 'Timed out',
    })
    expect(store.pendingConfirmationKeys()).toEqual([])
  })

  it('merges snapshot messages without replacing realtime edits or restoring removed identities', () => {
    const { store } = createMessages()
    store.upsert({ id: 'updated', content: 'before' })
    store.upsert({ id: 'removed', content: 'before' })
    const atRequest = store.captureIdentitySnapshot()
    store.upsert({ id: 'updated', content: 'live' })
    store.removeByIds(new Set(['removed']))
    store.mergeSessionSnapshot([
      { id: 'updated', content: 'older' }, { id: 'removed', content: 'older' }, { id: 'new', content: 'snapshot' },
    ], atRequest)
    expect(store.messages.value).toEqual([{ id: 'updated', content: 'live' }, { id: 'new', content: 'snapshot' }])
  })
})
