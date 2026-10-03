import { effectScope, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useChatHistory } from '../message/useChatHistory'
import { useChatMessageContext } from '@/composables/useChatMessageContext'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))

const setup = () => {
  const scope = effectScope()
  const container = document.createElement('div')
  Object.defineProperty(container, 'scrollHeight', { configurable: true, value: 1000 })
  const restore = vi.fn().mockResolvedValue(true)
  const applyHistoryPage = vi.fn()
  const history = scope.run(() => useChatHistory({
    getWorkspaceId: () => 'w', getCurrentTask: () => ({ id: 'task' }),
    route: reactive({ params: { taskId: 'task' }, query: {} }), router: { replace: vi.fn() },
    historyContext: useChatMessageContext(),
    messages: { reset: vi.fn(), replaceAll: vi.fn(), captureIdentitySnapshot: () => new Map(), applyHistoryPage, appendPage: vi.fn() },
    terminalLogs: { clear: vi.fn(), restoreFromHistory: vi.fn() },
    cards: { syncConfirmationCards: vi.fn() },
    highlight: { highlightedMessageId: { value: '' }, scheduleClear: vi.fn(), clear: vi.fn() },
    getChatContainer: () => container, restoreWorkbenchScroll: restore, scrollToChatBottom: vi.fn(),
  }))!
  api.get.mockResolvedValue({ data: { messages: [], logs: [], has_more: true } })
  return { scope, container, restore, history, applyHistoryPage }
}

describe('chat history scroll continuity', () => {
  it('restores the saved view once on entry, without restoring old positions on later snapshots', async () => {
    const runtime = setup()
    try {
      await runtime.history.loadHistory('task')
      expect(runtime.restore).toHaveBeenCalledOnce()
      runtime.container.scrollTop = 680
      await runtime.history.loadHistory('task')
      expect(runtime.restore).toHaveBeenCalledOnce()
      expect(runtime.container.scrollTop).toBe(680)
      runtime.history.resetPaging()
      await runtime.history.loadHistory('task')
      expect(runtime.restore).toHaveBeenCalledTimes(2)
    } finally { runtime.scope.stop() }
  })

  it('preserves the original offset when older messages are prepended near the top', async () => {
    const runtime = setup()
    try {
      await runtime.history.loadHistory('task')
      runtime.container.scrollTop = 32
      runtime.applyHistoryPage.mockImplementation(() => {
        Object.defineProperty(runtime.container, 'scrollHeight', { value: 1600 })
      })
      await runtime.history.loadOlderMessages()
      expect(runtime.container.scrollTop).toBe(632)
    } finally { runtime.scope.stop() }
  })
})
