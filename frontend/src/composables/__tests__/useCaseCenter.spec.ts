import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { wsId: 'ws-1' }, query: {} }),
  useRouter: () => routerMock,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { useCaseCenter } from '@/composables/useCaseCenter'

const caseItem = (overrides: Record<string, unknown> = {}) => ({
  id: 'case-1',
  workspace_id: 'ws-1',
  creator_id: 'user-1',
  source_task_id: 'task-1',
  title: '连接池耗尽排查',
  status: 'DRAFT',
  category: 'PRODUCT',
  priority: 'P0',
  my_can_manage: true,
  my_can_review: false,
  review_records: [],
  ...overrides,
})

describe('useCaseCenter', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.put.mockReset()
    apiMock.delete.mockReset()
    routerMock.push.mockReset()
    routerMock.replace.mockReset()
  })

  it('loads the case list with keyword and filter params', async () => {
    apiMock.get.mockResolvedValueOnce({
      data: { items: [caseItem()], total: 1, page: 1, page_size: 20 },
    })
    const vm = useCaseCenter()
    vm.keyword.value = '连接池'
    vm.category.value = 'PRODUCT'
    vm.status.value = 'DRAFT'
    vm.priority.value = 'P0'
    await vm.loadCases({ reset: true })

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/cases', {
      params: { page: 1, page_size: 20, keyword: '连接池', category: 'PRODUCT', status: 'DRAFT', priority: 'P0' },
    })
    expect(vm.items.value).toHaveLength(1)
    expect(vm.total.value).toBe(1)
  })

  it('opens case detail and exposes permission flags', async () => {
    apiMock.get.mockResolvedValueOnce({ data: caseItem({ my_can_review: true }) })
    const vm = useCaseCenter()
    await vm.openCase('case-1')

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/cases/case-1')
    expect(vm.currentCase.value?.id).toBe('case-1')
    expect(vm.myCanManage.value).toBe(true)
    expect(vm.myCanReview.value).toBe(true)
  })

  it('submits a draft case for review through the state machine endpoint', async () => {
    apiMock.get.mockResolvedValue({ data: caseItem() })
    apiMock.post.mockResolvedValueOnce({ data: caseItem({ status: 'PENDING_REVIEW' }) })
    const vm = useCaseCenter()
    await vm.openCase('case-1')
    await vm.submitCase()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/cases/case-1/submit')
  })

  it('decides an in-review case with approve conclusion and comment', async () => {
    apiMock.get.mockResolvedValue({ data: caseItem({ status: 'IN_REVIEW' }) })
    apiMock.post.mockResolvedValueOnce({ data: caseItem({ status: 'APPROVED' }) })
    const vm = useCaseCenter()
    await vm.openCase('case-1')
    vm.reviewConclusion.value = 'approve'
    vm.reviewComment.value = '根因清晰，同意入库'
    await vm.confirmReview()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/cases/case-1/review', {
      conclusion: 'approve',
      comment: '根因清晰，同意入库',
    })
  })

  it('saves a new case through the create endpoint', async () => {
    apiMock.get.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } })
    apiMock.post.mockResolvedValueOnce({ data: caseItem() })
    const vm = useCaseCenter()
    vm.openCreateForm()
    vm.formModel.value.title = '白屏问题定位'
    await vm.saveForm()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/cases', expect.objectContaining({ title: '白屏问题定位' }))
  })

  it('deletes a case through the delete endpoint', async () => {
    apiMock.get.mockResolvedValue({ data: caseItem() })
    apiMock.delete.mockResolvedValueOnce({ data: { msg: 'ok' } })
    const vm = useCaseCenter()
    await vm.openCase('case-1')
    await vm.deleteCase()

    expect(apiMock.delete).toHaveBeenCalledWith('/workspaces/ws-1/cases/case-1')
    expect(vm.currentCase.value).toBeNull()
    expect(vm.drawerOpen.value).toBe(false)
  })
})
