import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import RagQueueDetailView from '@/views/RagQueueDetailView.vue'
import * as ragOutboxOps from '@/composables/rag/ragOutboxOps'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const routeMock = vi.hoisted(() => ({
  params: { queueId: 'q1' },
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  back: vi.fn(),
}))

const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMock,
  useRouter: () => routerMock,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: { value: 'zh' } }),
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>
  return {
    ...actual,
    ElMessage: messageMock,
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

const sampleCases: any[] = [
  {
    id: 'c1',
    doc_key: 'case:case-1',
    title: '案例一',
    workspace_id: 'w1',
    version: 1,
    status: 'QUEUED',
    exported_at: null,
  },
  {
    id: 'c2',
    doc_key: 'case:case-2',
    title: '案例二',
    workspace_id: 'w1',
    version: 2,
    status: 'EXPORTED',
    exported_at: '2026-08-26T12:00:00',
  },
]

const mockDetail = (cases: any[] = sampleCases) => {
  apiMock.get.mockImplementation((url: string) => {
    const path = String(url)
    if (path.includes('/export.zip')) {
      return Promise.resolve({ data: new Blob(['pk'], { type: 'application/zip' }) })
    }
    if (path.includes('/export.md')) {
      return Promise.resolve({ data: new Blob(['---\n# case'], { type: 'text/markdown' }) })
    }
    if (path.includes('/cases')) {
      return Promise.resolve({
        data: { items: cases, total: cases.length, page: 1, page_size: 200 },
      })
    }
    return Promise.resolve({
      data: {
        id: 'q1',
        name: 'RAG-228f39dc-20260826-001',
        workspace_id: 'w1',
        status: 'RUNNING',
        case_count: 2,
        exported_count: 0,
        created_at: '2026-08-26T10:00:00',
        consumed_at: null,
      },
    })
  })
  apiMock.post.mockImplementation(() => Promise.resolve({ data: {} }))
}

const mountDetail = async () => {
  const wrapper = mount(RagQueueDetailView, {
    global: {
      plugins: [createPinia(), ElementPlus],
      mocks: { $t: (key: string) => key },
    },
  })
  await flushPromises()
  return wrapper
}

describe('RagQueueDetailView (案例同步队列·下钻详情页)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    routerMock.push.mockReset()
    routerMock.back.mockReset()
    messageMock.success.mockReset()
    messageMock.error.mockReset()
    messageMock.info.mockReset()
  })

  it('渲染队列信息（名称/状态/计数）与案例列表', async () => {
    mockDetail()
    const wrapper = await mountDetail()

    expect(wrapper.text()).toContain('RAG-228f39dc-20260826-001')
    expect(wrapper.text()).toContain('rag_queue.status_running')
    expect(wrapper.text()).toContain('案例一')
    expect(wrapper.text()).toContain('案例二')
    expect(wrapper.text()).toContain('rag_queue.case_status_queued')
    expect(wrapper.text()).toContain('rag_queue.case_status_exported')
    expect(wrapper.text()).toContain('rag_queue.download_case')
    expect(wrapper.text()).toContain('rag_queue.back')
  })

  it('点击「返回列表」调用 router.back（下钻页回退）', async () => {
    mockDetail()
    // jsdom 默认 history.length 为 1，模拟从列表页跳转进来的历史栈
    window.history.pushState({}, '', '/ops/rag-queue/q1')
    const wrapper = await mountDetail()

    const backBtn = wrapper.findAll('button').find((b) => b.text().includes('rag_queue.back'))
    expect(backBtn).toBeDefined()
    await backBtn!.trigger('click')
    expect(routerMock.back).toHaveBeenCalled()
  })

  it('单案例下载：用户取消保存 -> 不调用标记接口，提示未改变状态', async () => {
    mockDetail()
    const downloadSpy = vi
      .spyOn(ragOutboxOps, 'downloadRagQueueCase')
      .mockResolvedValue({ saved: false, canceled: true })
    const wrapper = await mountDetail()

    const caseDownloadBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('rag_queue.download_case'))
    expect(caseDownloadBtn).toBeDefined()
    await caseDownloadBtn!.trigger('click')
    await flushPromises()

    expect(downloadSpy).toHaveBeenCalledWith('q1', 'c1', expect.stringMatching(/\.md$/))
    const completeCall = apiMock.post.mock.calls.find((call) =>
      String(call[0]).includes('/export/complete'),
    )
    expect(completeCall).toBeUndefined()
    expect(messageMock.info).toHaveBeenCalled()
    expect(messageMock.success).not.toHaveBeenCalled()
  })

  it('单案例下载：保存成功后（已落盘）才调用确认标记接口', async () => {
    mockDetail()
    const downloadSpy = vi
      .spyOn(ragOutboxOps, 'downloadRagQueueCase')
      .mockResolvedValue({ saved: true, canceled: false })
    const wrapper = await mountDetail()

    const caseDownloadBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('rag_queue.download_case'))
    expect(caseDownloadBtn).toBeDefined()
    await caseDownloadBtn!.trigger('click')
    await flushPromises()

    expect(downloadSpy).toHaveBeenCalledWith('q1', 'c1', expect.stringMatching(/\.md$/))
    const completeCall = apiMock.post.mock.calls.find((call) =>
      String(call[0]).includes('/rag/queues/q1/cases/c1/export/complete'),
    )
    expect(completeCall).toBeDefined()
    expect(messageMock.success).toHaveBeenCalled()
  })

  it('整体队列下载：保存成功后（已落盘）才调用确认标记接口', async () => {
    mockDetail()
    const downloadZipSpy = vi
      .spyOn(ragOutboxOps, 'downloadRagQueueZip')
      .mockResolvedValue({ saved: true, canceled: false })
    const wrapper = await mountDetail()

    const queueDownloadBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('rag_queue.download'))
    expect(queueDownloadBtn).toBeDefined()
    await queueDownloadBtn!.trigger('click')
    await flushPromises()

    expect(downloadZipSpy).toHaveBeenCalledWith('q1', 'RAG-228f39dc-20260826-001')
    const completeCall = apiMock.post.mock.calls.find((call) =>
      String(call[0]).includes('/rag/queues/q1/export/complete'),
    )
    expect(completeCall).toBeDefined()
    expect(messageMock.success).toHaveBeenCalled()
  })
})