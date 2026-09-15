import { shallowRef } from 'vue'
import { describe, expect, it } from 'vitest'

import {
  useChatWorkbenchScroll,
  type ChatWorkbenchMode,
} from '@/composables/useChatWorkbenchScroll'

const scrollContainer = (scrollHeight: number, scrollTop = 0) => {
  const element = document.createElement('div')
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    value: scrollHeight,
  })
  element.scrollTop = scrollTop
  return element
}

describe('useChatWorkbenchScroll', () => {
  it('opens each view at the bottom first, then restores its previous position', async () => {
    const activeMode = shallowRef<ChatWorkbenchMode>('platform')
    const taskId = shallowRef('task-1')
    const state = useChatWorkbenchScroll({
      activeMode,
      getTaskId: () => taskId.value,
    })
    const platform = scrollContainer(1200, 640)
    const cli = scrollContainer(1800)
    state.chatContainer.value = platform
    state.setTerminalContainer(cli)

    await state.switchMode('cli')
    expect(cli.scrollTop).toBe(1800)

    cli.scrollTop = 260
    await state.switchMode('platform')
    expect(platform.scrollTop).toBe(640)

    platform.scrollTop = 420
    await state.switchMode('cli')
    expect(cli.scrollTop).toBe(260)

    await state.switchMode('platform')
    expect(platform.scrollTop).toBe(420)
  })

  it('keeps saved positions isolated by task', async () => {
    const activeMode = shallowRef<ChatWorkbenchMode>('platform')
    const taskId = shallowRef('task-1')
    const state = useChatWorkbenchScroll({
      activeMode,
      getTaskId: () => taskId.value,
    })
    const platform = scrollContainer(900, 315)
    state.chatContainer.value = platform
    state.rememberScrollPosition()

    taskId.value = 'task-2'
    platform.scrollTop = 0
    await state.restoreScrollPosition()
    expect(platform.scrollTop).toBe(900)

    taskId.value = 'task-1'
    await state.restoreScrollPosition()
    expect(platform.scrollTop).toBe(315)
  })
})
