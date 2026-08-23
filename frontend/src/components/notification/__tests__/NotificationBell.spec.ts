import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import api from '@/utils/api'
import type { AppNotificationItem } from '@/stores/notification'
import NotificationBell from '@/components/notification/NotificationBell.vue'

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/ws/ws-1/dashboard' }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/utils/ws', () => ({
  buildBackendWsUrl: () => 'ws://localhost/ws',
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ isAuthenticated: true, token: 'test-token' }),
}))

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

class FakeWebSocket {
  onopen: unknown = null
  onmessage: unknown = null
  onerror: unknown = null
  onclose: unknown = null
  close() {}
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

interface BellWrapper {
  vm: { $nextTick: () => Promise<void> }
  find: (selector: string) => { element: HTMLElement; trigger: (event: string) => Promise<void> }
  unmount: () => void
}

const makeItem = (overrides: Partial<AppNotificationItem> = {}): AppNotificationItem => ({
  id: 'n-1',
  workspace_id: 'ws-1',
  type: 'pre_input_mention',
  title: 'someone @了你',
  body: 'hello',
  payload: { task_id: 'task-9', workspace_id: 'ws-1' },
  read_at: null,
  created_at: new Date().toISOString(),
  ...overrides,
})

const flushAsync = () => new Promise((resolve) => setTimeout(resolve, 0))

const mountBell = async (): Promise<BellWrapper> => {
  const wrapper = mount(NotificationBell, {
    global: {
      plugins: [i18n, createPinia()],
    },
    attachTo: document.body,
  })
  await wrapper.vm.$nextTick()
  return wrapper as unknown as BellWrapper
}

const openPopover = async (wrapper: BellWrapper) => {
  const button = wrapper.find('button.notification-nav-item').element
  button.getBoundingClientRect = () => ({
    x: 0, y: 700, top: 700, bottom: 740, left: 0, right: 200, width: 200, height: 40,
    toJSON: () => ({}),
  } as DOMRect)
  await wrapper.find('button.notification-nav-item').trigger('click')
  await flushAsync()
  await wrapper.vm.$nextTick()
}

const firePointerDown = (element: HTMLElement) => {
  element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
}

describe('NotificationBell', () => {
  beforeEach(() => {
    window.innerHeight = 768
    routerPush.mockReset()
    vi.mocked(api.get).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.delete).mockReset()
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('renders popover teleported to body with fixed position anchored right of the bell', async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 1 } }
      return { data: { items: [makeItem()], total: 1 } }
    })

    const wrapper = await mountBell()
    await openPopover(wrapper)

    const popover = document.body.querySelector('.notification-popover') as HTMLElement | null
    expect(popover).not.toBeNull()
    // Teleport 到 body:定位节点脱离组件子树,不再受侧栏 overflow:hidden 裁剪
    const anchor = document.body.querySelector('.notification-popover-anchor') as HTMLElement | null
    expect(anchor).not.toBeNull()
    expect(anchor!.closest('.notification-bell-wrap')).toBeNull()
    expect(anchor!.style.position).toBe('fixed')
    expect(anchor!.style.left).toBe('208px')
    expect(anchor!.style.bottom).toBe('74px')

    wrapper.unmount()
  })

  it('consumes on click: deletes the item and navigates to the target chat', async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 1 } }
      return { data: { items: [makeItem()], total: 1 } }
    })
    vi.mocked(api.delete).mockResolvedValue({ data: { ok: true, was_unread: true } })

    const wrapper = await mountBell()
    await openPopover(wrapper)

    const rows = document.body.querySelectorAll('.notification-item')
    expect(rows.length).toBe(1)
    ;(rows[0] as HTMLElement).click()
    await flushAsync()

    expect(api.delete).toHaveBeenCalledWith('/notifications/n-1')
    expect(routerPush).toHaveBeenCalledWith('/ws/ws-1/chat/task-9')
    expect(document.body.querySelector('.notification-popover')).toBeNull()

    wrapper.unmount()
  })

  it('removes a single item via the X button without navigating', async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 1 } }
      return { data: { items: [makeItem()], total: 1 } }
    })
    vi.mocked(api.delete).mockResolvedValue({ data: { ok: true, was_unread: true } })

    const wrapper = await mountBell()
    await openPopover(wrapper)

    ;(document.body.querySelector('.item-remove') as HTMLElement).click()
    await flushAsync()

    expect(api.delete).toHaveBeenCalledWith('/notifications/n-1')
    expect(routerPush).not.toHaveBeenCalled()
    // 弹层保持打开,列表项被乐观移除
    expect(document.body.querySelector('.notification-popover')).not.toBeNull()
    expect(document.body.querySelectorAll('.notification-item').length).toBe(0)

    wrapper.unmount()
  })

  it('clears all notifications from the header action', async () => {
    const items = [makeItem(), makeItem({ id: 'n-2', read_at: new Date().toISOString() })]
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 1 } }
      return { data: { items, total: 2 } }
    })
    vi.mocked(api.delete).mockResolvedValue({ data: { deleted: 2, unread_deleted: 1 } })

    const wrapper = await mountBell()
    await openPopover(wrapper)

    const clearBtn = [...document.body.querySelectorAll('.header-btn')]
      .find((btn) => btn.textContent?.includes('清空')) as HTMLElement | undefined
    expect(clearBtn).toBeTruthy()
    clearBtn!.click()
    await flushAsync()

    expect(api.delete).toHaveBeenCalledWith('/notifications')
    expect(document.body.querySelectorAll('.notification-item').length).toBe(0)

    wrapper.unmount()
  })

  it('closes the popover on outside pointerdown and Escape', async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 0 } }
      return { data: { items: [], total: 0 } }
    })

    const wrapper = await mountBell()
    await openPopover(wrapper)
    expect(document.body.querySelector('.notification-popover')).not.toBeNull()

    // 弹层内部 pointerdown 不关闭
    firePointerDown(document.body.querySelector('.notification-popover') as HTMLElement)
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.notification-popover')).not.toBeNull()

    // 外部 pointerdown 关闭
    const outside = document.createElement('div')
    document.body.appendChild(outside)
    firePointerDown(outside)
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.notification-popover')).toBeNull()
    outside.remove()

    // Escape 关闭
    await openPopover(wrapper)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.notification-popover')).toBeNull()

    wrapper.unmount()
  })

  it('falls back to consume-without-navigation for unknown types', async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('unread-count')) return { data: { count: 1 } }
      return { data: { items: [makeItem({ type: 'future_system_notice', payload: null })], total: 1 } }
    })
    vi.mocked(api.delete).mockResolvedValue({ data: { ok: true, was_unread: true } })

    const wrapper = await mountBell()
    await openPopover(wrapper)

    ;(document.body.querySelector('.notification-item') as HTMLElement).click()
    await flushAsync()

    // 未注册类型:仍消费删除,但不跳转
    expect(api.delete).toHaveBeenCalledWith('/notifications/n-1')
    expect(routerPush).not.toHaveBeenCalled()

    wrapper.unmount()
  })
})
