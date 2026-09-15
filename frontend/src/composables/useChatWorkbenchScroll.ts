import { nextTick, shallowRef, type Ref } from 'vue'

export type ChatWorkbenchMode = 'platform' | 'cli'
type ChatScrollTarget = 'chat' | 'terminal'

interface UseChatWorkbenchScrollOptions {
  activeMode: Ref<ChatWorkbenchMode>
  getTaskId: () => string
}

const scrollPositionKey = (taskId: string, mode: ChatWorkbenchMode) => `${taskId}:${mode}`

export const useChatWorkbenchScroll = ({
  activeMode,
  getTaskId,
}: UseChatWorkbenchScrollOptions) => {
  const chatContainer = shallowRef<HTMLElement | null>(null)
  const terminalContainer = shallowRef<HTMLElement | null>(null)
  const scrollPositions = new Map<string, number>()

  const containerFor = (mode: ChatWorkbenchMode) => (
    mode === 'platform' ? chatContainer.value : terminalContainer.value
  )

  const rememberScrollPosition = (
    mode: ChatWorkbenchMode = activeMode.value,
    taskId: string = getTaskId(),
  ) => {
    const container = containerFor(mode)
    if (!taskId || !container) return
    scrollPositions.set(scrollPositionKey(taskId, mode), container.scrollTop)
  }

  const restoreScrollPosition = async (
    mode: ChatWorkbenchMode = activeMode.value,
    taskId: string = getTaskId(),
  ): Promise<boolean> => {
    await nextTick()
    if (!taskId || taskId !== getTaskId() || mode !== activeMode.value) return false

    const container = containerFor(mode)
    if (!container) return false

    const savedPosition = scrollPositions.get(scrollPositionKey(taskId, mode))
    container.scrollTop = savedPosition ?? container.scrollHeight
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
    await nextTick()
    const container = containerFor(target === 'chat' ? 'platform' : 'cli')
    if (container) container.scrollTop = container.scrollHeight
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
    setTerminalContainer,
    switchMode,
  }
}
