import { beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PlaybookLibrary from '../PlaybookLibrary.vue'
import PlaybookDetailView from '../PlaybookDetailView.vue'
import PlaybookDetailDialog from '../PlaybookDetailDialog.vue'
import api from '@/utils/api'

const pushMock = vi.fn()
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => ({ push: pushMock }),
    useRoute: () => ({ path: '/workspaces/ws/cases', params: { wsId: 'ws', playbookId: 'spec' }, query: {} }),
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => (k === 'case_center.search' ? '检索' : k) }),
}))

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } }))

const item = {
  id: 'spec',
  workspace_id: 'ws',
  title: '支付异常',
  version: '1',
  validation_state: 'SCHEMA_VALID',
  inputs: {},
  match: { symptoms: ['重复入账'] },
}

beforeEach(() => {
  vi.resetAllMocks()
  pushMock.mockReset()
})

it('uses server pages, resets pagination for search, and routes to detail page on click', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [item], total: 25 } })
  const wrapper = mount(PlaybookLibrary, {
    props: { workspaceId: 'ws' },
    global: { stubs: { RouterLink: true } },
  })
  await flushPromises()

  // 翻页
  await wrapper.findAll('.pl-pagination button')[1]!.trigger('click')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases/playbooks', {
    params: { page: 2, page_size: 12, keyword: '' },
  })

  // 搜索
  await wrapper.get('.search-input').setValue('空指针')
  await wrapper.get('.search-input').trigger('keyup.enter')
  await flushPromises()
  expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws/cases/playbooks', {
    params: { page: 1, page_size: 12, keyword: '空指针' },
  })

  // 点击标题跳转到独立路由页面
  await wrapper.get('.pl-title-link').trigger('click')
  expect(pushMock).toHaveBeenCalledWith({
    name: 'workspacePlaybookDetail',
    params: { wsId: 'ws', playbookId: 'spec' },
  })

  // 点击卡片底部查看详情按钮也跳转到独立路由
  await wrapper.get('.card-footer .btn-secondary').trigger('click')
  expect(pushMock).toHaveBeenLastCalledWith({
    name: 'workspacePlaybookDetail',
    params: { wsId: 'ws', playbookId: 'spec' },
  })

  wrapper.unmount()
})

it('edits detail fields and saves a new version in PlaybookDetailView', async () => {
  vi.mocked(api.get).mockResolvedValue({
    data: {
      can_edit: true,
      document: {
        metadata: { id: 'guide', title: '支付异常', version: '1' },
        execution: { mode: 'ANALYSIS_GUIDE' },
        match: { symptoms: ['重复入账'] },
        context: { summary: '摘要' },
        stages: [{ id: 'collect', objective: '采证' }],
      },
    },
  })
  vi.mocked(api.put).mockResolvedValue({ data: { id: 'new' } })

  const wrapper = mount(PlaybookDetailView, {
    global: { stubs: { RouterLink: true } },
  })
  await flushPromises()

  expect(wrapper.text()).toContain('支付异常')
  expect(wrapper.find('.pd-title-input').exists()).toBe(false)

  // 点击编辑
  await wrapper.get('.pd-actions .btn-primary').trigger('click')
  expect(wrapper.find('.pd-title-input').exists()).toBe(true)

  // 修改标题
  await wrapper.get('.pd-title-input').setValue('新的规程标题')

  // 添加新步骤
  await wrapper.get('.pd-card-header button.btn-sm').trigger('click')
  await wrapper.findAll('.step-item textarea')[1]!.setValue('复现验证')

  // 保存
  await wrapper.get('.pd-actions .btn-primary').trigger('click')
  await flushPromises()

  const putCall = vi.mocked(api.put).mock.calls[0]
  expect(putCall).toBeDefined()
  expect(putCall![0]).toBe('/workspaces/ws/cases/playbooks/spec')
  const body = putCall![1] as any
  expect(body.document.metadata.title).toBe('新的规程标题')
  expect(body.document.stages[1].id).toMatch(/^step_[a-z0-9]+$/)

  // 点击返回列表，验证带 tab=playbooks
  await wrapper.get('.btn-back').trigger('click')
  expect(pushMock).toHaveBeenCalledWith({
    name: 'workspaceCases',
    params: { wsId: 'ws' },
    query: { tab: 'playbooks' },
  })

  wrapper.unmount()
})

it('retains backward compatibility for PlaybookDetailDialog', async () => {
  vi.mocked(api.get).mockResolvedValue({
    data: {
      can_edit: true,
      document: {
        metadata: { id: 'guide', title: '支付异常', version: '1' },
        execution: { mode: 'ANALYSIS_GUIDE' },
        match: { symptoms: ['重复入账'] },
        context: { summary: '摘要' },
        stages: [{ id: 'collect', objective: '采证' }],
      },
    },
  })
  vi.mocked(api.put).mockResolvedValue({ data: { id: 'new' } })
  const wrapper = mount(PlaybookDetailDialog, {
    props: { item },
    global: { stubs: { teleport: true, RouterLink: true } },
  })
  await flushPromises()
  expect(wrapper.get('input').attributes('readonly')).toBeDefined()
  await wrapper.get('footer .btn-primary').trigger('click')
  await wrapper.get('input').setValue('新的标题')
  await wrapper.get('.pd-body .btn-secondary').trigger('click')
  await wrapper.findAll('.pd-step textarea')[1]!.setValue('复现验证')
  await wrapper.get('footer .btn-primary').trigger('click')
  await flushPromises()
  const body = vi.mocked(api.put).mock.calls[0]![1] as any
  expect(body.document.metadata.title).toBe('新的标题')
  expect(body.document.stages[1].id).toMatch(/^[a-z][a-z0-9_]*$/)
  expect(wrapper.emitted('saved')).toHaveLength(1)
  wrapper.unmount()
})

it('opens ConfirmActionModal on clicking delete button and deletes playbook', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [item], total: 1 } })
  vi.mocked(api.delete).mockResolvedValue({ data: { id: 'spec' } })

  const wrapper = mount(PlaybookLibrary, {
    props: { workspaceId: 'ws' },
    global: { stubs: { RouterLink: true, teleport: true } },
  })
  await flushPromises()

  // 初始时确认删除弹窗未打开
  const confirmModal = wrapper.findComponent({ name: 'ConfirmActionModal' })
  expect(confirmModal.exists()).toBe(true)
  expect(confirmModal.props('show')).toBe(false)

  // 找到卡片上的 DeleteActionButton 并触发点击
  const deleteBtn = wrapper.findComponent({ name: 'DeleteActionButton' })
  expect(deleteBtn.exists()).toBe(true)
  await deleteBtn.trigger('click')

  // 弹窗展开并显示对应标题
  expect(confirmModal.props('show')).toBe(true)
  expect(confirmModal.props('emphasisValue')).toBe('支付异常')

  // 点击弹窗确认
  confirmModal.vm.$emit('confirm')
  await flushPromises()

  // 验证调用了对应的 DELETE 接口并刷新了列表
  expect(api.delete).toHaveBeenCalledWith('/workspaces/ws/cases/playbooks/spec')
  expect(api.get).toHaveBeenCalledTimes(2)
  expect(confirmModal.props('show')).toBe(false)

  wrapper.unmount()
})

