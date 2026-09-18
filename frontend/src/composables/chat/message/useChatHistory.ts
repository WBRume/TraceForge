import { nextTick, ref, watch } from 'vue'
import api from '@/utils/api'
import { ElMessage } from 'element-plus'
import type { useChatMessageContext } from '@/composables/useChatMessageContext'
import { mapHistoryMessages } from '../shared/messageIdentity'

type HistoryContext = ReturnType<typeof useChatMessageContext>

/**
 * 历史消息加载：分页历史、锚点上下文（定位某条消息的历史窗口）、
 * 向上翻页的滚动位置保持、路由 messageId 联动。
 * 历史代次（generation）守护所有在途请求：会话切换/撤销后旧响应一律丢弃。
 */
export function useChatHistory(options: {
  getWorkspaceId: () => string
  getCurrentTask: () => any
  route: any
  router: any
  historyContext: HistoryContext
  messages: {
    reset: () => void
    replaceAll: (items: any[]) => void
    captureIdentitySnapshot: () => Map<string, any>
    applyHistoryPage: (mapped: any[], reset: boolean, snapshot?: Map<string, any>) => void
    appendPage: (mapped: any[], direction: 'before' | 'after') => void
  }
  terminalLogs: {
    clear: () => void
    restoreFromHistory: (logs: any[]) => void
  }
  cards: {
    syncConfirmationCards: () => void
  }
  highlight: {
    highlightedMessageId: { value: string }
    scheduleClear: () => void
    clear: () => void
  }
  getChatContainer: () => HTMLElement | null
  restoreWorkbenchScroll: (taskId: string) => Promise<boolean>
  scrollToChatBottom: () => void
}) {
  const { historyContext } = options

  const currentPage = ref(1)
  const hasMore = ref(false)
  const loadingMore = ref(false)
  let historyGeneration = 0

  const bumpGeneration = () => {
    historyGeneration += 1
  }

  const isCurrentTaskId = (taskId: string) => (
    String(options.getCurrentTask()?.id || '') === String(taskId)
  )

  const highlightMessageFromRouteQuery = async (): Promise<boolean> => {
    const messageId = String(options.route.query.messageId || '').trim()
    if (!messageId) return false
    options.highlight.highlightedMessageId.value = messageId
    await nextTick()
    const target = options.getChatContainer()?.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
    if (target) {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    options.highlight.scheduleClear()
    return Boolean(target)
  }

  const loadHistory = async (taskId: string, reset: boolean = true) => {
    if (reset && options.route.query.messageId && String(options.route.params.taskId) === taskId) {
      await loadAnchorContext(String(options.route.query.messageId))
      return
    }
    if (reset) historyContext.reset()
    const requestGeneration = ++historyGeneration
    try {
      if (reset) {
        currentPage.value = 1
      }

      // 请求前先记录身份快照：期间新增的本地消息（如正在发送的气泡）不会被快照覆盖
      const identitySnapshot = reset ? options.messages.captureIdentitySnapshot() : undefined

      const res = await api.get(`/workspaces/${options.getWorkspaceId()}/tasks/${taskId}/history`, {
        params: { page: currentPage.value, page_size: 50 }
      })
      if (requestGeneration !== historyGeneration || !isCurrentTaskId(taskId)) return
      const { messages: hMessages, logs: hLogs, has_more } = res.data
      hasMore.value = has_more

      const mapped = mapHistoryMessages(hMessages)

      if (reset) {
        options.messages.applyHistoryPage(mapped, true, identitySnapshot)
        options.cards.syncConfirmationCards()
        // 还原终端日志（仅首次加载）
        options.terminalLogs.restoreFromHistory(hLogs)

        await nextTick()
        if (options.route.query.messageId) {
          await highlightMessageFromRouteQuery()
        } else {
          await options.restoreWorkbenchScroll(taskId)
        }
      } else {
        // 向上加载更早消息：prepend 到列表前面
        options.messages.applyHistoryPage(mapped, false)
      }
    } catch (e) {
      console.error('Failed to load history', e)
    }
  }

  const loadAnchorContext = async (messageId: string) => {
    const taskId = String(options.getCurrentTask()?.id || '')
    if (!taskId) return
    bumpGeneration()
    options.messages.reset()
    try {
      const result = await historyContext.load(options.getWorkspaceId(), taskId, messageId)
      if (!result || !isCurrentTaskId(taskId)) return
      options.messages.replaceAll(mapHistoryMessages(result.messages))
      hasMore.value = result.has_before
      await highlightMessageFromRouteQuery()
    } catch (error: any) {
      if (error.code !== 'ERR_CANCELED') ElMessage.warning(error.response?.status === 404 ? '该消息已被撤销或删除' : '历史上下文暂不可用，请回到最新会话')
    }
  }

  const loadContextDirection = async (direction: 'before' | 'after') => {
    const task = options.getCurrentTask()
    if (!task || historyContext.loading.value) return
    const container = options.getChatContainer()
    const oldHeight = container?.scrollHeight || 0
    const oldTop = container?.scrollTop || 0
    try {
      const result = await historyContext.more(options.getWorkspaceId(), task.id, direction)
      if (!result) return
      const mapped = mapHistoryMessages(result.messages)
      options.messages.appendPage(mapped, direction)
      hasMore.value = Boolean(historyContext.context.value?.has_before)
      await nextTick()
      if (container && direction === 'before') container.scrollTop = oldTop + container.scrollHeight - oldHeight
    } catch { ElMessage.warning('历史窗口已失效，请重新定位或回到最新') }
  }

  const returnToLatest = async () => {
    historyContext.reset()
    const query = { ...options.route.query }
    delete query.messageId
    await options.router.replace({ query })
    const taskId = String(options.getCurrentTask()?.id || '')
    if (taskId) await loadHistory(taskId, true)
    await nextTick()
    options.scrollToChatBottom()
  }

  const loadOlderMessages = async () => {
    const task = options.getCurrentTask()
    if (historyContext.anchored.value) { await loadContextDirection('before'); return }
    if (!hasMore.value || loadingMore.value || !task) return

    loadingMore.value = true
    const container = options.getChatContainer()
    const prevScrollHeight = container?.scrollHeight || 0

    currentPage.value++
    try {
      await loadHistory(task.id, false)

      // 保持滚动位置不跳动
      await nextTick()
      if (container) {
        const newScrollHeight = container.scrollHeight
        container.scrollTop = newScrollHeight - prevScrollHeight
      }
    } finally {
      loadingMore.value = false
    }
  }

  const handleChatScroll = () => {
    const container = options.getChatContainer()
    if (!container) return
    // 滚动到顶部附近时加载更早消息
    if (container.scrollTop < 50 && hasMore.value && !loadingMore.value) {
      void loadOlderMessages()
    }
  }

  const resetPaging = () => {
    currentPage.value = 1
    hasMore.value = false
  }

  // 路由 messageId 联动：定位/回到最新
  watch(() => String(options.route.query.messageId || ''), (messageId, old) => {
    const currentTaskId = String(options.getCurrentTask()?.id || '')
    if (messageId && messageId !== old && currentTaskId === String(options.route.params.taskId)) void loadAnchorContext(messageId)
    else if (!messageId && historyContext.anchored.value) {
      historyContext.reset()
      if (currentTaskId) void loadHistory(currentTaskId, true)
    }
  })

  return {
    currentPage,
    hasMore,
    loadingMore,
    bumpGeneration,
    loadHistory,
    loadAnchorContext,
    loadContextDirection,
    returnToLatest,
    loadOlderMessages,
    handleChatScroll,
    highlightMessageFromRouteQuery,
    resetPaging,
  }
}
