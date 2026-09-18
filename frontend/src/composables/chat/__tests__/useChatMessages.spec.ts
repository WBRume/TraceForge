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
})
