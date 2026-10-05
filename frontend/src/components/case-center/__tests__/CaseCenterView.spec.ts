import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CaseCenterView from '../CaseCenterView.vue'
import api from '@/utils/api'
const pushMock = vi.hoisted(() => vi.fn())

vi.mock('@/utils/api', () => ({ default: { get: vi.fn() } }))
vi.mock('vue-router', async () => ({
  ...await vi.importActual('vue-router'),
  useRoute: () => ({ params: { wsId: 'ws' }, query: {} }),
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }))

const mountList = () => mount(CaseCenterView, {
  props: { workspaceId: 'ws', embedded: true },
  global: { stubs: { CaseFormDialog: true, CasePromotionAction: true, PlaybookLibrary: true } },
})

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.get).mockImplementation(async (_url, options) => {
    const page = options?.params.page || 1
    return { data: { items: [{
      id: `case-${page}`, workspace_id: 'ws', title: `案例第 ${page} 页`,
      category: 'PRODUCT', priority: 'P2', status: 'APPROVED', my_can_manage: true,
      has_playbook: false, created_at: '2026-10-05T12:00:00', review_round: 1,
    }], total: 41 } }
  })
})

it('shows pagination and replaces each page while preserving selected cases for promotion', async () => {
  const wrapper = mountList()
  await flushPromises()
  const pager = wrapper.get('nav[aria-label="案例分页"]')
  expect(pager.text()).toContain('1 / 3')
  expect(pager.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  expect(wrapper.find('table[aria-label="排查案例库"]').exists()).toBe(true)
  await wrapper.get('.cc-row input[type="checkbox"]').setValue(true)
  await pager.findAll('button')[1]!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('案例第 2 页')
  expect(wrapper.text()).not.toContain('案例第 1 页')
  expect(pager.text()).toContain('2 / 3')
  expect(wrapper.findComponent({ name: 'CasePromotionAction' }).props('caseIds')).toEqual(['case-1'])
  await pager.findAll('button')[0]!.trigger('click')
  await flushPromises()
  expect((wrapper.get('.cc-row input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
  wrapper.unmount()
})

it('sorts all pages, applies advanced criteria, and keeps draft text out of paging requests', async () => {
  const wrapper = mountList()
  await flushPromises()
  const calls = vi.mocked(api.get).mock.calls.length
  await wrapper.get('button[aria-label="按优先级排序"]').trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenCalledTimes(calls + 1)
  expect(wrapper.get('th[aria-sort="ascending"]').text()).toBe('优先级')
  expect(wrapper.text()).not.toContain('排序字段')
  expect(wrapper.text()).not.toContain('排序方向')
  await wrapper.get('[aria-controls="case-advanced-filters"]').trigger('click')
  await wrapper.get('input[placeholder="输入产品名称"]').setValue('网关')
  await wrapper.get('.cc-pagination button:last-child').trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 2, page_size: 20, sort_by: 'priority', sort_order: 'asc',
  } })
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, sort_by: 'priority', sort_order: 'asc', product_name: '网关',
  } })
  await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, sort_by: 'updated_at', sort_order: 'desc',
  } })
  expect((wrapper.get('input[placeholder="输入产品名称"]').element as HTMLInputElement).value).toBe('')
  wrapper.unmount()
})

it('changing sort preserves pending criteria and sorts only the applied query', async () => {
  const wrapper = mountList()
  await flushPromises()
  await wrapper.get('[aria-controls="case-advanced-filters"]').trigger('click')
  const product = wrapper.get('input[placeholder="输入产品名称"]')
  await product.setValue('已应用的产品')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  await product.setValue('尚未应用的产品')
  await wrapper.get('input[aria-label="案例关键词"]').setValue('待提交关键词')

  await wrapper.get('button[aria-label="按创建时间排序"]').trigger('click')
  await flushPromises()

  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, product_name: '已应用的产品', sort_by: 'created_at', sort_order: 'desc',
  } })
  expect((product.element as HTMLInputElement).value).toBe('尚未应用的产品')
  expect((wrapper.get('input[aria-label="案例关键词"]').element as HTMLInputElement).value).toBe('待提交关键词')

  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, keyword: '待提交关键词', product_name: '尚未应用的产品', sort_by: 'created_at', sort_order: 'desc',
  } })
  wrapper.unmount()
})

it('rejects reversed date ranges before sending a query', async () => {
  const wrapper = mountList()
  await flushPromises()
  await wrapper.get('[aria-controls="case-advanced-filters"]').trigger('click')
  const dates = wrapper.findAll('input[type="date"]')
  await dates[0]!.setValue('2026-10-05')
  await dates[1]!.setValue('2026-10-01')
  const calls = vi.mocked(api.get).mock.calls.length
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('[role="alert"]').text()).toContain('开始日期不能晚于结束日期')
  expect(api.get).toHaveBeenCalledTimes(calls)
  wrapper.unmount()
})

it('toggles header sort direction and returns to the first page', async () => {
  const wrapper = mountList()
  await flushPromises()
  await wrapper.get('.cc-pagination button:last-child').trigger('click')
  await flushPromises()
  await wrapper.get('button[aria-label="按优先级排序"]').trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, sort_by: 'priority', sort_order: 'asc',
  } })
  await wrapper.get('button[aria-label="按优先级排序"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('th[aria-sort="descending"]').text()).toBe('优先级')
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases', { params: {
    page: 1, page_size: 20, sort_by: 'priority', sort_order: 'desc',
  } })
  wrapper.unmount()
})

it('selects only eligible cases in one workspace and supports partial and cleared selection', async () => {
  const makeCase = (id: string, extra: Record<string, unknown> = {}) => ({
    id, title: id, workspace_id: 'ws-a', category: 'PRODUCT', priority: 'P2',
    status: 'APPROVED', my_can_manage: true, created_at: '2026-10-05T12:00:00',
    review_round: 1, has_playbook: false, ...extra,
  })
  vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [
    makeCase('a'), makeCase('b'), makeCase('other', { workspace_id: 'ws-b' }),
    makeCase('draft', { status: 'DRAFT' }), makeCase('readonly', { my_can_manage: false }),
  ], total: 5 } })
  const wrapper = mount(CaseCenterView, {
    props: { workspaceId: '', embedded: true },
    global: { stubs: { CaseFormDialog: true, CasePromotionAction: true, PlaybookLibrary: true } },
  })
  await flushPromises()
  const pageSelection = wrapper.get('input[aria-label="选择本页可晋升案例"]')
  await wrapper.get('input[aria-label="选择案例：a"]').setValue(true)
  expect((pageSelection.element as HTMLInputElement).indeterminate).toBe(true)
  expect(wrapper.get('input[aria-label="选择案例：other"]').attributes('disabled')).toBeDefined()
  await pageSelection.setValue(true)
  expect(wrapper.findComponent({ name: 'CasePromotionAction' }).props('caseIds')).toEqual(['a', 'b'])
  expect((pageSelection.element as HTMLInputElement).indeterminate).toBe(false)
  expect(wrapper.get('input[aria-label="选择案例：draft"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('input[aria-label="选择案例：readonly"]').attributes('disabled')).toBeDefined()
  await pageSelection.setValue(false)
  expect(wrapper.findComponent({ name: 'CasePromotionAction' }).props('caseIds')).toEqual([])
  await pageSelection.setValue(true)
  await wrapper.get('.cc-clear-selection').trigger('click')
  expect((pageSelection.element as HTMLInputElement).checked).toBe(false)
  expect(wrapper.findComponent({ name: 'CasePromotionAction' }).props('caseIds')).toEqual([])
  wrapper.unmount()
})

it('opens the report from the title and details action', async () => {
  const wrapper = mountList()
  await flushPromises()
  await wrapper.get('.case-title-link').trigger('click')
  await wrapper.get('.detail-action').trigger('click')
  expect(pushMock).toHaveBeenCalledTimes(2)
  expect(pushMock).toHaveBeenLastCalledWith({ name: 'knowledgeCaseDetail', params: { wsId: 'ws', caseId: 'case-1' } })
  wrapper.unmount()
})
