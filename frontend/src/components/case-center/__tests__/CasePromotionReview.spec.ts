import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import CasePromotionReviewView from '@/views/CasePromotionReviewView.vue'
import CasePromotionReview from '../CasePromotionReview.vue'
import api from '@/utils/api'
vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { wsId: 'ws', jobId: 'job' }, path: '/workspaces/ws/cases' }), useRouter: () => ({ push: vi.fn() }) }))
const draft = { grouping_reason: '建议按触发条件分组', playbooks: [['a', 'b'], ['c']].map((ids, index) => ({
  title: `定位方法 ${index + 1}`, source_case_ids: ids, summary: '对比故障条件并逐项证伪', symptoms: ['间歇性失败'], steps: ['收集证据', '对照验证'],
})) }
const job = { job_id: 'job', workspace_id: 'ws', status: 'SUCCESS', progress: 100,
  cases: ['a', 'b', 'c'].map(id => ({ id, title: `案例 ${id}` })), result: { review_state: 'PENDING', draft_revision: 'rev', draft } }
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { items: [job] } }) })
const mountReview = () => mount(CasePromotionReviewView, { global: { plugins: [createPinia()], stubs: { ConfirmActionModal: true } } })
it('preserves edited draft across WS updates and only publishes on explicit confirmation', async () => {
  const wrapper = mountReview(); await flushPromises()
  expect(api.post).not.toHaveBeenCalled()
  const review = wrapper.findComponent(CasePromotionReview)
  await review.findAll('input')[0]!.setValue('人工修订的定位方法')
  window.dispatchEvent(new CustomEvent('playbook-promotion-updated', { detail: { workspace_id: 'ws' } }))
  await flushPromises()
  expect((review.findAll('input')[0]!.element as HTMLInputElement).value).toBe('人工修订的定位方法')
  vi.mocked(api.post).mockResolvedValue({ data: { ...job, result: { review_state: 'CONFIRMED', spec_ids: ['spec'] } } })
  review.vm.$emit('confirm'); await flushPromises()
  expect(api.post).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions/job/confirm', expect.objectContaining({
    draft: expect.objectContaining({ playbooks: expect.arrayContaining([expect.objectContaining({ title: '人工修订的定位方法' })]) }),
  }))
  wrapper.unmount()
})
it('follows a replacement job from the original review link', async () => {
  vi.mocked(api.get).mockImplementation(async (_url, config) => ({ data: { items: config?.params?.job_id === 'merged'
    ? [{ ...job, job_id: 'merged' }]
    : [{ ...job, result: { review_state: 'DISCARDED', replacement_job_id: 'merged' } }] } }))
  const wrapper = mountReview(); await flushPromises()
  expect(wrapper.findComponent(CasePromotionReview).exists()).toBe(true)
  expect(api.get).toHaveBeenCalledWith('/workspaces/ws/cases/playbook-promotions', { params: { job_id: 'merged' } })
  expect(api.post).not.toHaveBeenCalled()
  wrapper.unmount()
})
