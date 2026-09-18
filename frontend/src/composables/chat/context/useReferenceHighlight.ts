import { ref } from 'vue'

/**
 * 引用高亮状态：定位结果（上下文窗口引用 / 路由 messageId）命中的消息或
 * 终端日志高亮 2.6s 后自动清除。两种高亮共享同一个清除定时器，新的高亮
 * 总是取代旧的高亮与定时器；滚动定位由调用方完成（各自的容器知识不同）。
 */
export function useReferenceHighlight() {
  const highlightedMessageId = ref('')
  const highlightedTerminalLogId = ref('')
  let clearTimer: number | null = null

  const clear = () => {
    if (clearTimer !== null) {
      window.clearTimeout(clearTimer)
      clearTimer = null
    }
    highlightedMessageId.value = ''
    highlightedTerminalLogId.value = ''
  }

  const scheduleClear = () => {
    if (clearTimer !== null) {
      window.clearTimeout(clearTimer)
    }
    clearTimer = window.setTimeout(() => {
      highlightedMessageId.value = ''
      highlightedTerminalLogId.value = ''
      clearTimer = null
    }, 2600)
  }

  return {
    highlightedMessageId,
    highlightedTerminalLogId,
    clear,
    scheduleClear,
  }
}
