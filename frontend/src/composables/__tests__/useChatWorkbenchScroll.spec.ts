import { effectScope, nextTick, shallowRef, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  useChatWorkbenchScroll,
  type ChatWorkbenchMode,
} from '@/composables/useChatWorkbenchScroll'

const scopes: EffectScope[] = []
const useScroll = (options: Parameters<typeof useChatWorkbenchScroll>[0]) => {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => useChatWorkbenchScroll(options))!
}
class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []
  private callback: () => void
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  constructor(callback: () => void) {
    this.callback = callback
    ResizeObserverMock.instances.push(this)
  }
  resize() { this.callback() }
}
beforeEach(() => {
  ResizeObserverMock.instances = []
  vi.stubGlobal('ResizeObserver', ResizeObserverMock)
})
afterEach(() => {
  scopes.splice(0).forEach(scope => scope.stop())
  vi.unstubAllGlobals()
})

const scrollContainer = (scrollHeight: number, scrollTop = 0, clientHeight = 0) => {
  const element = document.createElement('div')
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    value: scrollHeight,
  })
  Object.defineProperty(element, 'clientHeight', { configurable: true, value: clientHeight })
  element.scrollTop = scrollTop
  return element
}

describe('useChatWorkbenchScroll', () => {
  it('opens each view at the bottom first, then restores its previous position', async () => {
    const activeMode = shallowRef<ChatWorkbenchMode>('platform')
    const taskId = shallowRef('task-1')
    const state = useScroll({
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
    const state = useScroll({
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

  it('retains the saved reading position while a task remounts with an empty history', async () => {
    const taskId = shallowRef('task-1')
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => taskId.value })
    const container = scrollContainer(900, 315, 400)
    state.chatContainer.value = container
    state.rememberScrollPosition()
    taskId.value = 'task-2'
    await nextTick()
    await state.restoreScrollPosition()
    taskId.value = 'task-1'
    Object.defineProperty(container, 'scrollHeight', { value: 0 })
    container.scrollTop = 0
    await nextTick()
    container.dispatchEvent(new Event('scroll'))
    Object.defineProperty(container, 'scrollHeight', { value: 900 })
    await state.restoreScrollPosition()
    expect(container.scrollTop).toBe(315)
  })

  it('follows content and viewport resizing at the bottom, and stops when the user scrolls up', async () => {
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => 'task' })
    const container = scrollContainer(1200, 800, 400)
    state.chatContainer.value = container
    await nextTick()
    const observer = ResizeObserverMock.instances.at(-1)!
    Object.defineProperty(container, 'clientHeight', { value: 250 })
    observer.resize()
    expect(container.scrollTop).toBe(1200)
    container.scrollTop = 200
    container.dispatchEvent(new Event('scroll'))
    Object.defineProperty(container, 'scrollHeight', { value: 1800 })
    observer.resize()
    state.followToBottom('chat')
    await nextTick()
    expect(container.scrollTop).toBe(200)
    await state.scrollToBottom('chat')
    Object.defineProperty(container, 'scrollHeight', { value: 2100 })
    observer.resize()
    expect(container.scrollTop).toBe(2100)
  })

  it('keeps a saved bottom position attached when the content grows in another view', async () => {
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => 'task' })
    const container = scrollContainer(1200, 800, 400)
    state.chatContainer.value = container
    state.setTerminalContainer(scrollContainer(2000))
    await state.switchMode('cli')
    Object.defineProperty(container, 'scrollHeight', { value: 1900 })
    await state.switchMode('platform')
    expect(container.scrollTop).toBe(1900)
  })

  it('does not override a user scroll when a reply arrives before the scroll event', async () => {
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => 'task' })
    const container = scrollContainer(1200, 800, 400)
    state.chatContainer.value = container
    await nextTick()
    container.scrollTop = 350
    Object.defineProperty(container, 'scrollHeight', { value: 1800 })
    await state.followToBottom('chat')
    ResizeObserverMock.instances.at(-1)!.resize()
    expect(container.scrollTop).toBe(350)
  })

  it('does not follow during history paging or apply a queued scroll to another task', async () => {
    const taskId = shallowRef('task-1')
    const paging = shallowRef(true)
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => taskId.value, canFollow: () => !paging.value })
    const container = scrollContainer(1200, 800, 400)
    state.chatContainer.value = container
    await nextTick()
    Object.defineProperty(container, 'scrollHeight', { value: 2000 })
    ResizeObserverMock.instances.at(-1)!.resize()
    expect(container.scrollTop).toBe(800)
    const pending = state.scrollToBottom('chat')
    taskId.value = 'task-2'
    container.scrollTop = 350
    await pending
    expect(container.scrollTop).toBe(350)
  })

  it('disconnects layout observers when the composable scope is disposed', async () => {
    const state = useScroll({ activeMode: shallowRef('platform'), getTaskId: () => 'task' })
    state.chatContainer.value = scrollContainer(1200)
    await nextTick()
    const observer = ResizeObserverMock.instances.at(-1)!
    scopes.at(-1)!.stop()
    expect(observer.disconnect).toHaveBeenCalledOnce()
  })
})
