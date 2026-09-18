import { ref } from 'vue'
import { nextTick } from 'vue'
import { useTaskContextWindow } from '@/composables/useTaskContextWindow'
import type { ContextCompactionLocatePayload, ContextTokenCategory } from '@/types/contextWindow'

/**
 * 上下文窗口面板：抽屉开关/层级、数据加载与防抖刷新（WS 事件高频触发，
 * 仅在抽屉打开时落地），以及压缩引用定位（切换工作台模式 + 高亮 + 滚动）。
 */
export function useContextWindowPanel(options: {
  getWorkspaceId: () => string
  getTaskId: () => string
  getActiveJobId: () => string | null
  setWorkbenchMode: (mode: 'platform' | 'cli') => Promise<void>
  scrollToTerminalBottom: () => void
  highlight: {
    highlightedMessageId: { value: string }
    highlightedTerminalLogId: { value: string }
    clear: () => void
    scheduleClear: () => void
  }
}) {
  const drawerOpen = ref(false)
  const drawerLevel = ref<1 | 2 | 3>(1)
  let refreshTimer: number | null = null

  const contextWindow = useTaskContextWindow({
    getWorkspaceId: options.getWorkspaceId,
    getTaskId: options.getTaskId,
    getAiJobId: options.getActiveJobId,
  })

  const clearRefreshTimer = () => {
    if (refreshTimer !== null) {
      window.clearTimeout(refreshTimer)
      refreshTimer = null
    }
  }

  const refresh = async () => {
    if (!options.getTaskId()) return
    if (contextWindow.selectedCategory.value) {
      await contextWindow.loadCategory(contextWindow.selectedCategory.value)
      return
    }
    await contextWindow.loadSummary()
  }

  /** WS 事件驱动的防抖刷新：抽屉未打开时直接跳过（数据在打开时加载）。 */
  const scheduleRefresh = () => {
    if (!drawerOpen.value || !options.getTaskId()) return
    clearRefreshTimer()
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null
      void refresh()
    }, 900)
  }

  const openDrawer = async () => {
    if (!options.getTaskId()) return
    drawerOpen.value = true
    await contextWindow.loadSummary()
  }

  const closeDrawer = () => {
    drawerOpen.value = false
  }

  const updateDrawerLevel = (level: number) => {
    drawerLevel.value = Math.max(1, Math.min(3, Number(level || 1))) as 1 | 2 | 3
  }

  const selectCategory = async (category: ContextTokenCategory | string) => {
    if (!options.getTaskId()) return
    await contextWindow.loadCategory(category)
  }

  const attrSelectorValue = (value: string) => String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"')

  const scrollToElementByAttr = async (attr: string, value: string) => {
    await nextTick()
    window.requestAnimationFrame(() => {
      const selector = `[${attr}="${attrSelectorValue(value)}"]`
      const target = document.querySelector(selector)
      if (target instanceof HTMLElement) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
  }

  const locateReference = async (payload: ContextCompactionLocatePayload) => {
    options.highlight.clear()
    const messageId = String(payload.chat_message_id || '').trim()
    const logId = String(payload.log_id || '').trim()
    if (messageId) {
      await options.setWorkbenchMode('platform')
      drawerOpen.value = false
      options.highlight.highlightedMessageId.value = messageId
      await scrollToElementByAttr('data-message-id', messageId)
      options.highlight.scheduleClear()
      return
    }
    if (logId) {
      await options.setWorkbenchMode('cli')
      drawerOpen.value = false
      options.highlight.highlightedTerminalLogId.value = logId
      await scrollToElementByAttr('data-log-id', logId)
      options.highlight.scheduleClear()
      return
    }
    if (payload.ai_job_id) {
      await options.setWorkbenchMode('cli')
      drawerOpen.value = false
      options.scrollToTerminalBottom()
    }
  }

  /** 会话切换：关闭抽屉、复位层级、清空数据与刷新定时器。 */
  const resetForTask = () => {
    drawerOpen.value = false
    drawerLevel.value = 1
    contextWindow.reset()
    clearRefreshTimer()
  }

  return {
    drawerOpen,
    drawerLevel,
    contextWindow,
    refresh,
    scheduleRefresh,
    openDrawer,
    closeDrawer,
    updateDrawerLevel,
    selectCategory,
    locateReference,
    resetForTask,
    clearRefreshTimer,
  }
}
