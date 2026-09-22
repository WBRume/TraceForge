import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import PlaybookPicker from '../PlaybookPickerSidebar.vue'
import TaskCreateDialog from '../TaskCreateDialog.vue'
import CasePlaybookHistory from '@/components/case-center/CasePlaybookHistory.vue'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn() } }))
const item = { id: 'guide-1', title: '支付空返回排查', version: 'analysis-1', validation_state: 'SCHEMA_VALID', inputs: {}, match: {}, reasons: ['NullPointerException'], score: 1, source_case_refs: ['case-1'] }
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers()
  api.get.mockReset().mockResolvedValue({ data: { repositories: [], items: [] } })
  api.post.mockReset().mockImplementation(async (url: string) => url.endsWith('/playbook-recommendations')
    ? { data: { items: [item], total: 1 } } : { data: { task_id: 'task-1', job_id: 'job-1' } })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers() })

describe('case promotion and task creation playbook workflow', () => {
  const selectDiagnosisType = async (wrapper: VueWrapper) => {
    await wrapper.findAll('.task-type-card').find((card) => card.text().includes('task_types.diagnosis'))!.trigger('click')
    await flushPromises()
  }

  it('hides the playbook entry for DEVELOPMENT tasks', async () => {
    wrapper = mount(TaskCreateDialog, { props: { wsId: 'ws-1' }, global: {
      plugins: [createPinia()], mocks: { $t: (key: string) => key },
    } })
    await flushPromises()
    expect(wrapper.find('.playbook-entry-card').exists()).toBe(false)
    await wrapper.get('input.primary-input').setValue('修复支付空返回')
    await wrapper.get('textarea').setValue('修复空返回问题')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const created = api.post.mock.calls.find(([url]) => url === '/workspaces/ws-1/tasks')
    expect(created?.[1]).toMatchObject({ task_type: 'DEVELOPMENT' })
    expect(created?.[1]).not.toHaveProperty('diagnosis_playbook_spec_id')
  })

  it('selects recommendations in a DIAGNOSIS task and submits selection with the task', async () => {
    wrapper = mount(TaskCreateDialog, { props: { wsId: 'ws-1' }, global: {
      plugins: [createPinia()], mocks: { $t: (key: string) => key },
    } })
    await flushPromises()
    await selectDiagnosisType(wrapper)
    await wrapper.get('input.primary-input').setValue('修复支付空返回')
    await wrapper.get('textarea').setValue('NullPointerException')
    await vi.advanceTimersByTimeAsync(300)
    expect(api.post).not.toHaveBeenCalled()
    await wrapper.get('.playbook-entry-card').trigger('click')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.text()).toContain('支付空返回排查')
    await wrapper.get('input[type="radio"]').setValue()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const created = api.post.mock.calls.find(([url]) => url === '/workspaces/ws-1/tasks')
    expect(created?.[1]).toMatchObject({ task_type: 'DIAGNOSIS', diagnosis_playbook_spec_id: 'guide-1', phenomenon: 'NullPointerException' })
    expect(wrapper.emitted('created')?.[0]?.[0]).toMatchObject({ taskId: 'task-1', jobId: 'job-1' })
  })

  it('ignores an old recommendation response and allows clearing the chosen guide', async () => {
    let resolveOld!: (value: unknown) => void
    api.post.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    wrapper = mount(PlaybookPicker, { props: { workspaceId: 'ws-1', open: true, name: 'old', description: '', taskType: 'DEVELOPMENT', modelValue: item }, global: { mocks: { $t: (key: string) => key } } })
    await vi.advanceTimersByTimeAsync(300)
    await wrapper.setProps({ name: 'new' })
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    resolveOld({ data: { items: [{ ...item, id: 'stale', title: '过期结果' }] } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('过期结果')
    await wrapper.findAll('button').find(button => button.text() === '取消选择')!.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([null])
  })

  it('recommendation errors do not prevent creating a diagnosis task', async () => {
    api.post.mockImplementation(async (url: string) => {
      if (url.endsWith('/playbook-recommendations')) throw new Error('offline')
      return { data: { task_id: 'task-1', job_id: 'job-1' } }
    })
    wrapper = mount(TaskCreateDialog, { props: { wsId: 'ws-1' }, global: { plugins: [createPinia()], mocks: { $t: (key: string) => key } } })
    await flushPromises()
    await selectDiagnosisType(wrapper)
    await wrapper.get('input.primary-input').setValue('定位支付异常')
    await wrapper.get('textarea').setValue('checkout 支付异常')
    await wrapper.get('.playbook-entry-card').trigger('click')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.text()).toContain('规程加载失败')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const created = api.post.mock.calls.find(([url]) => url === '/workspaces/ws-1/tasks')
    expect(created?.[1]).not.toHaveProperty('diagnosis_playbook_spec_id')
    expect(wrapper.emitted('created')).toHaveLength(1)
  })

  it('shows history without a single-case promotion action', async () => {
    wrapper = mount(CasePlaybookHistory, { props: { workspaceId: 'ws-1', caseId: 'case-1', canManage: true } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('晋升为诊断规程')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('paginates and searches only while open, preserving selection across pages', async () => {
    api.post.mockResolvedValue({ data: { items: [item], total: 17 } })
    wrapper = mount(PlaybookPicker, { props: { workspaceId: 'ws-1', open: false, name: 'payment', description: '', taskType: 'DEVELOPMENT', modelValue: item }, global: { mocks: { $t: (key: string) => key } } })
    await vi.advanceTimersByTimeAsync(500)
    expect(api.post).not.toHaveBeenCalled()
    await wrapper.setProps({ open: true })
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.find('.pagination-badge').text()).toBe('17')
    expect(wrapper.find('.skills-page-info').exists()).toBe(true)
    const nextBtn = wrapper.findAll('.page-nav-btn')[1]
    await nextBtn.trigger('click')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(api.post.mock.lastCall?.[1]).toMatchObject({ page: 2, page_size: 8 })
    expect(wrapper.text()).toContain('已选：支付空返回排查')
    await wrapper.get('input[type="search"]').setValue('checkout')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(api.post.mock.lastCall?.[1]).toMatchObject({ page: 1, keyword: 'checkout' })
    const count = api.post.mock.calls.length
    await wrapper.setProps({ open: false, name: 'changed while closed' })
    await vi.advanceTimersByTimeAsync(500)
    expect(api.post).toHaveBeenCalledTimes(count)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
