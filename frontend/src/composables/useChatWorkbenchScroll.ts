import { getCurrentScope, nextTick, onScopeDispose, shallowRef, watch, type Ref } from 'vue'

export type ChatWorkbenchMode = 'platform' | 'cli'
type ChatScrollTarget = 'chat' | 'terminal'

interface UseChatWorkbenchScrollOptions {
  activeMode: Ref<ChatWorkbenchMode>
  getTaskId: () => string
  canFollow?: () => boolean
}

const scrollPositionKey = (taskId: string, mode: ChatWorkbenchMode) => `${taskId}:${mode}`
const isAtBottom = (container: HTMLElement) => (
  container.scrollHeight - container.clientHeight - container.scrollTop <= 24
)

export const useChatWorkbenchScroll = ({
  activeMode,
  getTaskId,
  canFollow = () => true,
}: UseChatWorkbenchScrollOptions) => {
  const chatContainer = shallowRef<HTMLElement | null>(null)
  const terminalContainer = shallowRef<HTMLElement | null>(null)
  const scrollPositions = new Map<string, { top: number; atBottom: boolean }>()
  let followingBottom = true
  let alignActiveBottom: (() => void) | null = null
  let restoringView = true

  const containerFor = (mode: ChatWorkbenchMode) => (
    mode === 'platform' ? chatContainer.value : terminalContainer.value
  )

  const rememberScrollPosition = (
    mode: ChatWorkbenchMode = activeMode.value,
    taskId: string = getTaskId(),
  ) => {
    const container = containerFor(mode)
    if (!taskId || !container) return
    const key = scrollPositionKey(taskId, mode)
    scrollPositions.set(key, {
      top: container.scrollTop,
      atBottom: isAtBottom(container),
    })
  }

  // Content, pinned cards and the input can resize after the message render.
  // Keep the user's bottom intent across those changes, before the next paint.
  const stopObserving = watch(
    () => [containerFor(activeMode.value), getTaskId(), activeMode.value] as const,
    ([container, taskId, mode], _previous, onCleanup) => {
      if (!container || !taskId) return
      const key = scrollPositionKey(taskId, mode)
      restoringView = true
      followingBottom = scrollPositions.get(key)?.atBottom ?? true
      let lastTop = container.scrollTop
      let lastHeight = container.scrollHeight
      let lastClientHeight = container.clientHeight
      const updateGeometry = () => {
        lastTop = container.scrollTop
        lastHeight = container.scrollHeight
        lastClientHeight = container.clientHeight
      }
      const alignBottom = () => {
        // A wheel/scrollbar move may happen before its deferred scroll event.
        // Layout shrinkage can clamp scrollTop, so compare with the new maximum.
        const previousTop = Math.min(lastTop, Math.max(0, container.scrollHeight - container.clientHeight))
        if (container.scrollTop < previousTop - 24) followingBottom = false
        if (followingBottom && canFollow()) {
          container.scrollTop = container.scrollHeight
          if (!restoringView) rememberScrollPosition(mode, taskId)
        }
        updateGeometry()
      }
      const onScroll = () => {
        const layoutChanged = lastHeight !== container.scrollHeight || lastClientHeight !== container.clientHeight
        if (!layoutChanged && container.scrollTop !== lastTop) followingBottom = isAtBottom(container)
        if (layoutChanged) alignBottom()
        if (!restoringView) rememberScrollPosition(mode, taskId)
        updateGeometry()
      }
      alignActiveBottom = alignBottom
      container.addEventListener('scroll', onScroll, { passive: true })
      const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(alignBottom)
      resizeObserver?.observe(container)
      const observedChildren = new Set<Element>()
      const observeChildren = () => {
        for (const child of observedChildren) {
          if (child.parentElement === container) continue
          resizeObserver?.unobserve(child)
          observedChildren.delete(child)
        }
        for (const child of container.children) {
          if (observedChildren.has(child)) continue
          resizeObserver?.observe(child)
          observedChildren.add(child)
        }
      }
      observeChildren()
      const mutations = new MutationObserver(() => { observeChildren(); alignBottom() })
      mutations.observe(container, { childList: true, subtree: true, characterData: true, attributes: true })
      onCleanup(() => {
        container.removeEventListener('scroll', onScroll)
        resizeObserver?.disconnect()
        mutations.disconnect()
        alignActiveBottom = null
      })
    },
    { flush: 'post', immediate: true },
  )
  if (getCurrentScope()) onScopeDispose(stopObserving)

  const restoreScrollPosition = async (
    mode: ChatWorkbenchMode = activeMode.value,
    taskId: string = getTaskId(),
  ): Promise<boolean> => {
    await nextTick()
    if (!taskId || taskId !== getTaskId() || mode !== activeMode.value) return false

    const container = containerFor(mode)
    if (!container) return false

    const savedPosition = scrollPositions.get(scrollPositionKey(taskId, mode))
    followingBottom = savedPosition?.atBottom ?? true
    restoringView = false
    container.scrollTop = followingBottom ? container.scrollHeight : savedPosition!.top
    return true
  }

  const switchMode = async (mode: ChatWorkbenchMode) => {
    if (mode === activeMode.value) return

    const taskId = getTaskId()
    rememberScrollPosition(activeMode.value, taskId)
    activeMode.value = mode
    await restoreScrollPosition(mode, taskId)
  }

  const scrollToBottom = async (target: ChatScrollTarget) => {
    const taskId = getTaskId()
    const mode = target === 'chat' ? 'platform' : 'cli'
    if (mode !== activeMode.value) return
    followingBottom = true
    scrollPositions.set(scrollPositionKey(taskId, mode), { top: 0, atBottom: true })
    await nextTick()
    if (taskId !== getTaskId() || mode !== activeMode.value) return
    followingBottom = true
    const container = containerFor(mode)
    if (container) {
      restoringView = false
      container.scrollTop = container.scrollHeight
      rememberScrollPosition(mode, taskId)
    }
  }

  const followToBottom = async (target: ChatScrollTarget) => {
    const mode = target === 'chat' ? 'platform' : 'cli'
    const taskId = getTaskId()
    if (mode !== activeMode.value || !followingBottom || !canFollow()) return
    await nextTick()
    if (mode === activeMode.value && taskId === getTaskId() && canFollow()) alignActiveBottom?.()
  }

  const setTerminalContainer = (container: HTMLElement | null) => {
    terminalContainer.value = container
  }

  return {
    chatContainer,
    terminalContainer,
    rememberScrollPosition,
    restoreScrollPosition,
    scrollToBottom,
    followToBottom,
    setTerminalContainer,
    switchMode,
  }
}
