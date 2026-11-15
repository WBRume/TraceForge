import { describe, expect, it } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { useAutoHideHeader } from '@/composables/chat/useAutoHideHeader'

interface Scroller {
  element: HTMLDivElement
  scrollTo: (top: number) => void
  setScrollHeight: (height: number) => void
}

const createScroller = (top: number, scrollHeight = 2000, clientHeight = 400): Scroller => {
  const element = document.createElement('div')
  let currentTop = top
  let currentHeight = scrollHeight
  Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => currentHeight })
  Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => clientHeight })
  Object.defineProperty(element, 'scrollTop', {
    configurable: true,
    get: () => currentTop,
    set: (value: number) => { currentTop = value },
  })
  return {
    element,
    scrollTo: (next) => {
      currentTop = next
      element.dispatchEvent(new Event('scroll'))
    },
    setScrollHeight: (height) => { currentHeight = height },
  }
}

const mountAutoHide = async (scroller: Scroller, resetKey?: () => unknown) => {
  const container = ref<HTMLElement | null>(null)
  const scope = effectScope()
  const api = scope.run(() => useAutoHideHeader({ container, resetKey }))!
  container.value = scroller.element
  await nextTick()
  return { ...api, scope }
}

describe('useAutoHideHeader', () => {
  it('collapses when scrolling up and expands only at the bottom', async () => {
    const scroller = createScroller(1600)
    const { hidden, scope } = await mountAutoHide(scroller)
    expect(hidden.value).toBe(false)

    scroller.scrollTo(1400)
    expect(hidden.value).toBe(true)

    // 向下滚动但未到底：保持收起，避免中途反复弹出
    scroller.scrollTo(1500)
    expect(hidden.value).toBe(true)

    // 回到底部：展开
    scroller.scrollTo(1600)
    expect(hidden.value).toBe(false)

    scope.stop()
  })

  it('ignores tiny upward jitter until the threshold is reached', async () => {
    const scroller = createScroller(1200)
    const { hidden, scope } = await mountAutoHide(scroller)

    scroller.scrollTo(1194)
    expect(hidden.value).toBe(false)
    scroller.scrollTo(1188)
    expect(hidden.value).toBe(true)

    scope.stop()
  })

  it('stays expanded when scrolling up inside the bottom threshold', async () => {
    const scroller = createScroller(1600)
    const { hidden, scope } = await mountAutoHide(scroller)

    // 距底部 20px < 32px 阈值：仍在“读完待操作”区域
    scroller.scrollTo(1580)
    expect(hidden.value).toBe(false)

    scope.stop()
  })

  it('ignores scroll corrections caused by content height changes', async () => {
    const scroller = createScroller(1200)
    const { hidden, scope } = await mountAutoHide(scroller)

    // 内容撑高后浏览器为保持视图向上校正 scrollTop：不是用户回看
    scroller.setScrollHeight(2200)
    scroller.scrollTo(1120)
    expect(hidden.value).toBe(false)

    // 之后的真实向上滚动仍然会收起
    scroller.scrollTo(1100)
    expect(hidden.value).toBe(true)

    scope.stop()
  })

  it('reveals manually and resets on conversation switch', async () => {
    const taskId = ref('task-a')
    const scroller = createScroller(1600)
    const { hidden, reveal, reset, scope } = await mountAutoHide(scroller, () => taskId.value)

    scroller.scrollTo(1400)
    expect(hidden.value).toBe(true)

    reveal()
    expect(hidden.value).toBe(false)

    scroller.scrollTo(1300)
    expect(hidden.value).toBe(true)

    taskId.value = 'task-b'
    await nextTick()
    expect(hidden.value).toBe(false)

    scroller.scrollTo(1200)
    expect(hidden.value).toBe(true)
    reset()
    expect(hidden.value).toBe(false)

    scope.stop()
  })
})
