import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useChatViewModel } from '@/composables/chat/useChatViewModel'
import { useTaskRailStore } from '@/stores/taskRail'
import { clearWsCursorMemory } from '@/utils/wsCursor'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  defaults: { baseURL: 'http://localhost/api' },
}))

const routerMock = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))

// 路由必须是响应式的：任意导航都会替换 route.params（即使 wsId 不变）。
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  const route = reactive({
    params: { wsId: 'w', taskId: '' } as Record<string, string>,
    query: {} as Record<string, string>,
    path: '/workspaces/w/chat',
  })
  return {
    __route: route,
    useRoute: () => route,
    useRouter: () => routerMock,
    onBeforeRouteLeave: vi.fn(),
    onBeforeRouteUpdate: vi.fn(),
  }
})

vi.mock('@/utils/api', () => ({ default: apiMock }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    token: 'test-token',
    user: { id: 'u1', display_name: 'Tester' },
    fetchCurrentUser: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn(),
  }),
}))
vi.mock('@/stores/provisioning', () => ({
  useProvisioningStore: () => ({ taskListRefreshToken: 0, startWatching: vi.fn() }),
}))

class FakeWebSocket {
  static OPEN = 1
  readyState = 1
  onopen: ((event: any) => void) | null = null
  onmessage: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  onclose: ((event: any) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  url: string
  constructor(url: string) {
    this.url = url
  }
}

Object.defineProperty(globalThis, 'WebSocket', {
  writable: true,
  configurable: true,
  value: FakeWebSocket,
})

const resolveByUrl = (target: string) => {
  if (target.endsWith('/tasks')) return Promise.resolve({ data: { items: [], has_more: false, page: 1, page_size: 20 } })
  return Promise.resolve({ data: {} })
}

/** `/workspaces/:wsId/tasks` 的整表加载次数（不含单任务子资源）。 */
const taskListLoads = () => apiMock.get.mock.calls
  .filter(([url]) => String(url).endsWith('/tasks')).length

const listContainer = (scrollTop: number) => ({ scrollTop } as unknown as HTMLElement)

let wrapper: VueWrapper | null = null
let vm: ReturnType<typeof useChatViewModel>
let route: { params: Record<string, string>; query: Record<string, string>; path: string }

const mountViewModel = async () => {
  wrapper = mount(defineComponent({
    setup() {
      vm = useChatViewModel()
      return () => null
    },
  }))
  await flushPromises()
}

describe('useChatViewModel task list scope', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    clearWsCursorMemory()
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.get.mockImplementation((url: string) => resolveByUrl(String(url)))
    route = ((await import('vue-router')) as unknown as { __route: typeof route }).__route
    route.params = { wsId: 'w', taskId: '' }
    route.query = {}
    route.path = '/workspaces/w/chat'
    wrapper = null
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it('在选中会话（仅 taskId 变化的导航）后保留滚动位置且不重载列表', async () => {
    await mountViewModel()
    const container = listContainer(420)
    vm.taskListContainer.value = container
    const loadsBefore = taskListLoads()
    expect(loadsBefore).toBeGreaterThan(0)

    route.params = { wsId: 'w', taskId: 't2' }
    route.path = '/workspaces/w/chat/t2'
    await nextTick()
    await flushPromises()

    expect(taskListLoads()).toBe(loadsBefore)
    expect(container.scrollTop).toBe(420)
  })

  it('在查询参数变化（如跳转引用消息）后同样不重载列表', async () => {
    await mountViewModel()
    const container = listContainer(260)
    vm.taskListContainer.value = container
    const loadsBefore = taskListLoads()

    // 真实导航即使 wsId/taskId 不变也会替换 params（新对象、同值）
    route.params = { wsId: 'w', taskId: '' }
    route.query = { messageId: 'm-9' }
    await nextTick()
    await flushPromises()

    expect(taskListLoads()).toBe(loadsBefore)
    expect(container.scrollTop).toBe(260)
  })

  it('轨道视图切换仍然回到第一页并重置滚动位置', async () => {
    await mountViewModel()
    const container = listContainer(420)
    vm.taskListContainer.value = container
    const loadsBefore = taskListLoads()

    useTaskRailStore().selectView('following')
    await nextTick()
    await flushPromises()

    expect(taskListLoads()).toBe(loadsBefore + 1)
    expect(container.scrollTop).toBe(0)
  })

  it('切换工作区仍然重载并清空旧列表', async () => {
    await mountViewModel()
    const container = listContainer(420)
    vm.taskListContainer.value = container
    const loadsBefore = taskListLoads()

    route.params = { wsId: 'w2', taskId: '' }
    route.path = '/workspaces/w2/chat'
    await nextTick()
    await flushPromises()

    expect(taskListLoads()).toBe(loadsBefore + 1)
    expect(container.scrollTop).toBe(0)
    expect(apiMock.get.mock.calls.some(([url]) => String(url).includes('/workspaces/w2/tasks'))).toBe(true)
  })
})
