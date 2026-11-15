import { onScopeDispose, ref, watch, type Ref } from 'vue'

export interface UseAutoHideHeaderOptions {
  /** 会话消息滚动容器（ChatHistoryPanel 的 .chat-history） */
  container: Ref<HTMLElement | null>
  /** 距底部多少像素内视为“已读完”，重新展开工具栏 */
  bottomThreshold?: number
  /** 累计向上滚动多少像素后收起，避免触控板回弹造成抖动 */
  collapseThreshold?: number
  /** 会话切换等场景下重置为展开态 */
  resetKey?: () => unknown
}

/**
 * 会话工具栏滚动自动收起：
 * - 向上滚动（回看历史）→ 收起工具栏，给消息让出视野；
 * - 向下滚动未到底 → 保持当前状态；
 * - 向下滚动到最底部 → 展开，便于操作任务按钮与查看最新回复。
 * 仅切换工具栏显隐，不改动内容让位距离，避免滚动位置跳动。
 */
export const useAutoHideHeader = ({
  container,
  bottomThreshold = 32,
  collapseThreshold = 12,
  resetKey,
}: UseAutoHideHeaderOptions) => {
  const hidden = ref(false)
  let attached: HTMLElement | null = null
  let lastScrollTop = 0
  let lastScrollHeight = 0
  let upwardDistance = 0

  const distanceToBottom = (element: HTMLElement) => (
    element.scrollHeight - element.clientHeight - element.scrollTop
  )

  const reset = () => {
    hidden.value = false
    upwardDistance = 0
    lastScrollTop = attached?.scrollTop ?? 0
    lastScrollHeight = attached?.scrollHeight ?? 0
  }

  const handleScroll = () => {
    const element = container.value
    if (!element) return
    const top = element.scrollTop
    const delta = top - lastScrollTop
    const layoutChanged = element.scrollHeight !== lastScrollHeight
    lastScrollTop = top
    lastScrollHeight = element.scrollHeight

    // 回到底部：视为读完并准备操作，恢复工具栏
    if (distanceToBottom(element) <= bottomThreshold) {
      upwardDistance = 0
      hidden.value = false
      return
    }

    // 内容高度变化（流式追加、历史补齐、图片撑高）引起的 scrollTop 校正
    // 不算用户回看，保持当前显隐，避免工具栏意外收起
    if (layoutChanged) return

    // 向上回看历史：累计位移超过阈值后收起，避免 1~2px 抖动就闪隐
    if (delta < 0) {
      upwardDistance += -delta
      if (upwardDistance >= collapseThreshold) hidden.value = true
      return
    }

    // 向下滚动但尚未到底：保持收起，避免中途反复弹出
    if (delta > 0) upwardDistance = 0
  }

  const detach = () => {
    attached?.removeEventListener('scroll', handleScroll)
    attached = null
  }

  const attach = (element: HTMLElement | null) => {
    detach()
    attached = element
    if (!element) return
    element.addEventListener('scroll', handleScroll, { passive: true })
    reset()
  }

  watch(() => container?.value ?? null, (element) => attach(element), { immediate: true, flush: 'post' })

  if (resetKey) watch(resetKey, () => reset())

  // 收起后鼠标靠近顶部时手动召回（例如需要点击工具栏按钮）
  const reveal = () => {
    hidden.value = false
    upwardDistance = 0
  }

  onScopeDispose(detach)

  return { hidden, reveal, reset }
}
