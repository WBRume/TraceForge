import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import RagQueueView from '@/views/RagQueueView.vue'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: { value: 'zh' } }),
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  }
})

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => ({
    workspaces: [{ id: 'w1', name: '工作区A' }],
    fetchWorkspaces: vi.fn().mockResolvedValue(undefined),
  }),
}))

// jsdom lacks URL.createObjectURL
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:fake'
}
URL.revokeObjectURL = () => {}

// vitest 的全局 mockReset 会清空 setup.ts 注册的 matchMedia(vi.fn) 实现，
// 而 element-plus 内部 watch(useMediaQuery(...)) 依赖 window.matchMedia。
// 这里用普通函数重建 polyfill（非 vi mock，不受 mockReset 影响）。
const matchMediaPolyfill = (query: string): MediaQueryList =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  configurable: true,
  value: matchMediaPolyfill,
})

const sampleQueues: any[] = [
  {
    id: 'q1',
    name: 'RAG-228f39dc-20260826-001',
    workspace_id: 'w1',
    status: 'RUNNING',
    case_count: 3,
    exported_count: 1,
    created_at: '2026-08-26T10:00:00',
    consumed_at: null,
  },
  {
    id: 'q2',
    name: 'RAG-20260826-001',
    workspace_id: null,
    status: 'CONSUMED',
    case_count: 5,
    exported_count: 5,
    created_at: '2026-08-26T11:00:00',
    consumed_at: '2026-08-26T12:00:00',
  },
]

const mockQueuesList = (queues: any[] = sampleQueues) => {
  apiMock.get.mockImplementation((url: string) => {
    const path = String(url)
    if (path.includes('/export.zip') || path.includes('/export.md')) {
      return Promise.resolve({ data: {} })
    }
    return Promise.resolve({ data: { items: queues, total: queues.length, page: 1, page_size: 20 } })
  })
  apiMock.post.mockImplementation(() =>
    Promise.resolve({
      data: { id: 'q1', status: 'CONSUMED', case_count: 3, exported_count: 3 },
    }),
  )
}

const mountView = async () => {
  const wrapper = mount(RagQueueView, {
    global: {
      plugins: [createPinia(), ElementPlus],
      mocks: { $t: (key: string) => key },
    },
  })
  await flushPromises()
  return wrapper
}

describe('RagQueueView (案例同步队列·批次形态)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    routerMock.push.mockReset()
  })

  it('渲染标题、副标题与工具栏（工作区/状态筛选/刷新）', async () => {
    mockQueuesList([])
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('rag_queue.title')
    expect(wrapper.text()).toContain('rag_queue.subtitle')
    expect(wrapper.text()).toContain('rag_queue.workspace_all')
    expect(wrapper.text()).toContain('rag_queue.status_all')
    expect(wrapper.text()).toContain('rag_queue.refresh')
  })

  it('加载并渲染同步队列列表（名称/工作区/状态/案例数/操作）', async () => {
    mockQueuesList()
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('RAG-228f39dc-20260826-001')
    expect(wrapper.text()).toContain('RAG-20260826-001')
    expect(wrapper.text()).toContain('工作区A')
    expect(wrapper.text()).toContain('rag_queue.workspace_unassigned')
    expect(wrapper.text()).toContain('rag_queue.status_running')
    expect(wrapper.text()).toContain('rag_queue.status_consumed')
    expect(wrapper.text()).toContain('rag_queue.download')
    expect(wrapper.text()).toContain('rag_queue.download_again')
    expect(wrapper.text()).toContain('rag_queue.detail')
  })

  it('点击「查看案例」下钻到队列详情路由（不再使用抽屉）', async () => {
    mockQueuesList()
    const wrapper = await mountView()

    const detailBtn = wrapper.findAll('button').find((b) => b.text().includes('rag_queue.detail'))
    expect(detailBtn).toBeDefined()
    await detailBtn!.trigger('click')
    await flushPromises()

    expect(routerMock.push).toHaveBeenCalledWith('/ops/rag-queue/q1')
  })

  it('点击「下载队列」：拉取 ZIP -> 本地保存 -> 保存成功后才调用标记接口', async () => {
    mockQueuesList()
    const wrapper = await mountView()

    const downloadBtn = wrapper.findAll('button').find((b) => b.text().includes('rag_queue.download'))
    expect(downloadBtn).toBeDefined()
    await downloadBtn!.trigger('click')
    await flushPromises()

    const exportCall = apiMock.get.mock.calls.find((call) =>
      String(call[0]).includes('/rag/queues/q1/export.zip'),
    )
    expect(exportCall).toBeDefined()

    // 保存成功（jsdom 走 <a download> 降级路径）后才调用确认标记接口
    const completeCall = apiMock.post.mock.calls.find((call) =>
      String(call[0]).includes('/rag/queues/q1/export/complete'),
    )
    expect(completeCall).toBeDefined()
  })
})