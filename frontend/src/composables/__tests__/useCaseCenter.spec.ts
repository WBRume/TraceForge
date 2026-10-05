import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

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
    vm.status.value = 'DRAFT'
    vm.priority.value = 'P0'
    await vm.loadCases({ reset: true })

    expect(apiMock.get).toHaveBeenCalledWith('/workspaces/ws-1/cases', {
      params: { page: 1, page_size: 20, keyword: '连接池', status: 'DRAFT', priority: 'P0', sort_by: 'updated_at', sort_order: 'desc' },
    })
    expect(vm.items.value).toHaveLength(1)
    expect(vm.total.value).toBe(1)
  })

  it('loads all accessible cases when no workspace id is provided', async () => {
    apiMock.get.mockResolvedValueOnce({
      data: { items: [caseItem()], total: 1, page: 1, page_size: 20 },
    })
    const vm = useCaseCenter({ workspaceId: () => '' })
    await vm.loadCases({ reset: true })

    expect(apiMock.get).toHaveBeenCalledWith('/cases', {
      params: { page: 1, page_size: 20, sort_by: 'updated_at', sort_order: 'desc' },
    })
    expect(vm.items.value).toHaveLength(1)
  })

  it('replaces rows when paging, retains filters, and resets after changing page size', async () => {
    apiMock.get.mockResolvedValueOnce({ data: { items: [caseItem()], total: 42 } })
    const vm = useCaseCenter()
    vm.filters.category = 'PRODUCT'
    vm.filters.sort_by = 'priority'
    vm.filters.sort_order = 'asc'
    await vm.loadCases()
    apiMock.get.mockResolvedValueOnce({ data: { items: [caseItem({ id: 'case-2' })], total: 42 } })
    await vm.changePage(2)
    expect(vm.page.value).toBe(2)
    expect(vm.pageCount.value).toBe(3)
    expect(vm.items.value.map(item => item.id)).toEqual(['case-2'])
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-1/cases', { params: {
      page: 2, page_size: 20, category: 'PRODUCT', sort_by: 'priority', sort_order: 'asc',
    } })
    apiMock.get.mockResolvedValueOnce({ data: { items: [], total: 42 } })
    await vm.changePageSize(50)
    expect(vm.page.value).toBe(1)
    expect(vm.pageCount.value).toBe(1)
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-1/cases', { params: {
      page: 1, page_size: 50, category: 'PRODUCT', sort_by: 'priority', sort_order: 'asc',
    } })
  })

  it('sends advanced filters and clears them together on reset', async () => {
    apiMock.get.mockResolvedValue({ data: { items: [], total: 0 } })
    const vm = useCaseCenter()
    Object.assign(vm.filters, { product_name: ' 网关 ', product_version: '2.1', creator_name: '张', site_name: '华东',
      created_from: '2026-10-01', created_to: '2026-10-05', has_playbook: 'false' })
    await vm.applyFilters()
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-1/cases', { params: {
      page: 1, page_size: 20, sort_by: 'updated_at', sort_order: 'desc', product_name: '网关', product_version: '2.1',
      creator_name: '张', site_name: '华东', created_from: '2026-10-01', created_to: '2026-10-05', has_playbook: 'false',
    } })
    await vm.resetFilters()
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-1/cases', { params: {
      page: 1, page_size: 20, sort_by: 'updated_at', sort_order: 'desc',
    } })
  })

  it('ignores old results when switching workspace during a request', async () => {
    let resolveOld!: (result: unknown) => void
    apiMock.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const workspaceId = ref('ws-1')
    const vm = useCaseCenter({ workspaceId: () => workspaceId.value })
    const oldRequest = vm.loadCases()
    workspaceId.value = 'ws-2'
    apiMock.get.mockResolvedValueOnce({ data: { items: [caseItem({ id: 'new-case' })], total: 1 } })
    await vm.loadCases()
    resolveOld({ data: { items: [caseItem()], total: 9 } })
    await oldRequest
    expect(vm.items.value[0].id).toBe('new-case')
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-2/cases', { params: {
      page: 1, page_size: 20, sort_by: 'updated_at', sort_order: 'desc',
    } })
  })

  it('keeps only the latest query when responses arrive out of order', async () => {
    let resolveOld!: (result: unknown) => void
    apiMock.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const vm = useCaseCenter()
    const oldRequest = vm.loadCases()
    vm.keyword.value = '新的筛选'
    apiMock.get.mockResolvedValueOnce({ data: { items: [caseItem({ id: 'new-case' })], total: 1 } })
    await vm.applyFilters()
    resolveOld({ data: { items: [caseItem()], total: 42 } })
    await oldRequest
    expect(vm.items.value[0].id).toBe('new-case')
    expect(vm.total.value).toBe(1)
    expect(vm.loading.value).toBe(false)
  })

  it('returns to the last available page when the result count shrinks', async () => {
    const vm = useCaseCenter()
    apiMock.get.mockResolvedValueOnce({ data: { items: [], total: 21 } })
    apiMock.get.mockResolvedValueOnce({ data: { items: [caseItem()], total: 21 } })
    await vm.loadCases({ page: 3 })
    expect(vm.page.value).toBe(2)
    expect(vm.pageCount.value).toBe(2)
    expect(vm.items.value).toHaveLength(1)
    expect(apiMock.get).toHaveBeenLastCalledWith('/workspaces/ws-1/cases', { params: {
      page: 2, page_size: 20, sort_by: 'updated_at', sort_order: 'desc',
    } })
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

  it('decides an in-review case with approve conclusion and comment and closes dialog', async () => {
    apiMock.get.mockResolvedValue({ data: caseItem({ status: 'IN_REVIEW' }) })
    apiMock.post.mockResolvedValueOnce({ data: caseItem({ status: 'APPROVED' }) })
    const vm = useCaseCenter()
    await vm.openCase('case-1')
    vm.openReviewDialog('approve')
    expect(vm.reviewDialogVisible.value).toBe(true)

    vm.reviewComment.value = '根因清晰，同意入库'
    await vm.confirmReview()

    expect(apiMock.post).toHaveBeenCalledWith('/workspaces/ws-1/cases/case-1/review', {
      conclusion: 'approve',
      comment: '根因清晰，同意入库',
    })
    expect(vm.reviewDialogVisible.value).toBe(false)
    expect(vm.reviewComment.value).toBe('')
  })

  it('resets dialog visible and comment on closeReviewDialog', () => {
    const vm = useCaseCenter()
    vm.openReviewDialog('reject')
    vm.reviewComment.value = '需要补充链路'
    expect(vm.reviewDialogVisible.value).toBe(true)

    vm.closeReviewDialog()
    expect(vm.reviewDialogVisible.value).toBe(false)
    expect(vm.reviewComment.value).toBe('')
  })

  it('prevents rejection if comment is empty and keeps dialog open', async () => {
    apiMock.get.mockResolvedValue({ data: caseItem({ status: 'IN_REVIEW' }) })
    const vm = useCaseCenter()
    await vm.openCase('case-1')
    vm.openReviewDialog('reject')
    vm.reviewComment.value = '   '

    await vm.confirmReview()

    expect(apiMock.post).not.toHaveBeenCalledWith(
      expect.stringContaining('/review'),
      expect.anything(),
    )
    expect(vm.reviewDialogVisible.value).toBe(true)
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
