import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import CasePromotionAction from '../CasePromotionAction.vue'
import CasePromotionReview from '../CasePromotionReview.vue'
import api from '@/utils/api'
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const draft = { grouping_reason: '建议按触发条件分组', playbooks: [['a', 'b'], ['c']].map((ids, index) => ({
  title: `定位方法 ${index + 1}`, source_case_ids: ids, summary: '对比故障条件并逐项证伪', symptoms: ['间歇性失败'], steps: ['收集证据', '对照验证'],
})) }
const job = { job_id: 'job', workspace_id: 'ws', status: 'SUCCESS', progress: 100,
  cases: ['a', 'b', 'c'].map(id => ({ id, title: `案例 ${id}` })), result: { review_state: 'PENDING', draft_revision: 'rev', draft } }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { items: [job] } }) })
const mountAction = () => mount(CasePromotionAction, { props: { workspaceId: 'ws', caseIds: ['a','b','c'] }, global: {
  plugins: [createPinia()], stubs: { ConfirmActionModal: true, RequirementImportDialog: {
    props: ['open', 'reviewPending'], template: '<section v-if="open"><slot v-if="reviewPending" name="promotion" /></section>',
  } },
} })

it('shows two-plus-one as a reviewable draft and only confirms edited content on explicit click', async () => {
  const wrapper = mountAction(); await flushPromises()
  expect(wrapper.emitted('completed')).toBeUndefined()
  expect(api.post).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click'); await flushPromises()
  const review = wrapper.findComponent(CasePromotionReview)
  expect(review.text()).toContain('2 套规程')
  expect(review.text()).toContain('案例 c')
  await review.findAll('input')[0]!.setValue('人工修订的定位方法')
  window.dispatchEvent(new CustomEvent('playbook-promotion-updated', { detail: { workspace_id: 'ws' } }))
  await flushPromises()
  expect((review.findAll('input')[0]!.element as HTMLInputElement).value).toBe('人工修订的定位方法')
  vi.mocked(api.post).mockResolvedValue({ data: { ...job, result: { ...job.result, review_state: 'CONFIRMED', spec_ids: ['spec1','spec2'] } } })
  await review.get('.btn-primary').trigger('click'); await flushPromises()
  expect(api.post).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions/job/confirm', expect.objectContaining({ draft_revision: 'rev', draft: expect.objectContaining({ playbooks: expect.arrayContaining([expect.objectContaining({ title: '人工修订的定位方法' })]) }) }))
  expect(wrapper.emitted('completed')).toHaveLength(1)
  wrapper.unmount()
})

it('requests model re-abstraction instead of publishing or concatenating two groups', async () => {
  const wrapper = mountAction(); await flushPromises()
  await wrapper.get('button').trigger('click'); await flushPromises()
  vi.mocked(api.post).mockResolvedValue({ data: { job_id: 'merged', workspace_id: 'ws', status: 'PENDING', progress: 0 } })
  const button = wrapper.findAll('button').find(b => b.text() === '全部合并，重新提炼')!
  await button.trigger('click'); await flushPromises()
  expect(api.post).toHaveBeenCalledOnce()
  expect(api.post).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions/job/regenerate', { draft_revision: 'rev', idempotency_key: expect.any(String) })
  expect(wrapper.emitted('completed')).toBeUndefined()
  wrapper.unmount()
})

it('restores a regenerated draft from the original dialog link after refresh', async () => {
  vi.mocked(api.get).mockImplementation(async (_url, config) => ({ data: { items: config?.params?.job_id === 'merged'
    ? [{ ...job, job_id: 'merged' }]
    : [{ ...job, result: { review_state: 'DISCARDED', replacement_job_id: 'merged' } }] } }))
  const wrapper = mount(CasePromotionAction, { props: { workspaceId: 'ws', caseIds: [], requestedJobId: 'job' }, global: {
    plugins: [createPinia()], stubs: { ConfirmActionModal: true, RequirementImportDialog: true },
  } })
  await flushPromises()
  expect(wrapper.findComponent({ name: 'RequirementImportDialog' }).props('previewJob').job_id).toBe('merged')
  expect(wrapper.text()).toContain('确认晋升草案')
  expect(api.post).not.toHaveBeenCalled()
  wrapper.unmount()
})
